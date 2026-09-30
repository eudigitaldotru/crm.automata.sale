"""
tg_gateway_client.py — клиент локальной CRM к TG-Gateway (РАБОТАЕТ В РФ).

Заменяет сломанный tg_listener.py. Вместо прямого коннекта к Telegram
(заблокирован РКН) — опрашивает gateway на зарубежном VPS через HTTPS.
Исходящие запросы на 8443/443 проходят белые списки мобильного провайдера.

КЛЮЧЕВЫЕ ОСОБЕННОСТИ:
  - КУРСОР: last_seq сохраняется в файл между перезапусками. Если ПК был
    выключен, при включении клиент продолжит с последней позиции —
    без дубликатов (сообщения копятся в SQLite gateway).
  - МЭТЧИНГ: отправитель сопоставляется с клиентами по нормализованному
    телефону (без +/пробелов/скобок), username, tg_id и имени.
    Известные → в 20_Inbox/ (с привязкой к клиенту).
    Новые → в 15_Leads/ как лиды.

Запуск:
    python3 scripts/tg_gateway_client.py

Настройка в .env:
    TG_GATEWAY_URL=http://your-vps-ip:8443
    TG_GATEWAY_TOKEN=<GATEWAY_TOKEN с VPS>
"""
from sec_guard import guard_open, guard_urlopen

import os
import re
import sys
import json
import time
import uuid
import urllib.request
import urllib.error
import ssl
from pathlib import Path

# --- КОНФИГУРАЦИЯ ---
BASE = Path(__file__).resolve().parent.parent
GATEWAY_URL = os.getenv("TG_GATEWAY_URL", "https://localhost:8443").rstrip("/")
GATEWAY_TOKEN = os.getenv("TG_GATEWAY_TOKEN", "")
POLL_INTERVAL = 5  # сек между опросами (если gateway не держит long-poll)

# Файл-курсор: хранит последний обработанный seq (переживает перезапуски ПК)
CURSOR_FILE = BASE / "scripts" / ".tg_gateway_cursor"

# Загружаем .env из vault
try:
    from dotenv import load_dotenv
    load_dotenv(BASE / ".env")
    GATEWAY_URL = os.getenv("TG_GATEWAY_URL", GATEWAY_URL).rstrip("/")
    GATEWAY_TOKEN = os.getenv("TG_GATEWAY_TOKEN", GATEWAY_TOKEN)
except ImportError:
    pass

INBOX_DIR = BASE / "20_Inbox"
OUTBOX_DIR = BASE / "20_Outbox"
LEADS_DIR = BASE / "15_Leads"
TICKETS_DIR = BASE / "45_Tickets"
CLIENTS_DIR = BASE / "10_Clients"

# SSL: игнорируем проверку self-signed сертификата
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE


# ---------------------------------------------------------------------------
# Курсор last_seq (переживает перезапуск ПК — нет дубликатов)
# ---------------------------------------------------------------------------
def load_cursor() -> int:
    """Возвращает последний обработанный seq (0 если файла нет)."""
    try:
        return int(CURSOR_FILE.read_text().strip())
    except Exception:
        return 0


def save_cursor(seq: int):
    """Сохраняет курсор. Вызывать после обработки каждого пакета."""
    try:
        CURSOR_FILE.write_text(str(seq))
    except Exception as e:
        print(f"⚠️ не удалось сохранить курсор: {e}")


# ---------------------------------------------------------------------------
# HTTP к gateway
# ---------------------------------------------------------------------------
def gateway_get(path):
    url = f"{GATEWAY_URL}{path}"
    req = urllib.request.Request(url, method="GET")
    if GATEWAY_TOKEN:
        req.add_header("Authorization", f"Bearer {GATEWAY_TOKEN}")
    try:
        with guard_urlopen(req, timeout=35, context=_SSL_CTX) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"❌ gateway GET {path}: {e}")
        return None


def gateway_post(path, body):
    url = f"{GATEWAY_URL}{path}"
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if GATEWAY_TOKEN:
        req.add_header("Authorization", f"Bearer {GATEWAY_TOKEN}")
    try:
        with guard_urlopen(req, timeout=15, context=_SSL_CTX) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"⚠️ gateway POST {path}: {e}")
        return None


# ---------------------------------------------------------------------------
# Нормализация и мэтчинг клиентов
# ---------------------------------------------------------------------------
def normalize_phone(raw: str) -> str:
    """
    Приводит телефон к каноничному виду (только цифры).
    '+7 (927) 123-70-15' → '79271237015'
    '8 927 123 70 15'   → '79271237015' (российская 8→7)
    """
    if not raw:
        return ""
    digits = re.sub(r"\D", "", str(raw))
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    return digits


def load_clients():
    """
    Возвращает структуру для мэтчинга:
      {'phones': {phone_digits: client_name},
       'usernames': {username_lower: client_name},
       'tg_ids': {tg_id: client_name},
       'names': {name_lower: client_name}}
    Читает telegram/phone/tg_id/contact_name/company_name из frontmatter.
    """
    import yaml
    data = {"phones": {}, "usernames": {}, "tg_ids": {}, "names": {}, "chats": {}}
    for f in CLIENTS_DIR.glob("*.md"):
        try:
            content = f.read_text(encoding="utf-8")
            m = re.search(r"^\s*---\n(.*?)\n---", content, re.DOTALL)
            if not m:
                continue
            meta = yaml.safe_load(m.group(1)) or {}
            name = f.stem

            # Телефон
            for key in ("phone", "contact_phone"):
                val = normalize_phone(meta.get(key, ""))
                if val:
                    data["phones"][val] = name

            # Telegram: username (@name) ИЛИ телефон в поле telegram
            tg_raw = str(meta.get("telegram") or meta.get("tg") or meta.get("tg_username") or "").strip()
            if tg_raw:
                stripped = tg_raw.lstrip("@")
                # username — только латиница/цифры/_, не цифры в начале
                if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", stripped):
                    data["usernames"][stripped.lower()] = name
                else:
                    # похоже на телефон
                    ph = normalize_phone(tg_raw)
                    if ph:
                        data["phones"][ph] = name

            # tg_id
            tg_id = str(meta.get("tg_id") or "").strip()
            if tg_id:
                data["tg_ids"][tg_id] = name

            # Имя контакта (только длинные, > 3 символов)
            for key in ("contact_name", "company_name"):
                cname = str(meta.get(key) or "").strip().lower()
                if cname and len(cname) > 3:
                    data["names"][cname] = name

            # Привязанные рабочие группы (tg_chats) — их слушаем ПОЛНОСТЬЮ
            chats_raw = meta.get("tg_chats") or []
            chat_items = chats_raw if isinstance(chats_raw, list) else [chats_raw]
            for it in chat_items:
                cid = str(it.get("id") if isinstance(it, dict) else it).strip()
                if cid:
                    data["chats"][cid] = name
        except Exception:
            pass
    return data


def match_sender(sender: dict, known: dict):
    """
    Сопоставляет отправителя с известным клиентом.
    Возвращает имя клиента или None (новый контакт → лид).
    """
    # 1. tg_id (самый надёжный)
    tg_id = str(sender.get("id") or "").strip()
    if tg_id and tg_id in known["tg_ids"]:
        return known["tg_ids"][tg_id]

    # 2. username
    username = str(sender.get("username") or "").strip().lower().lstrip("@")
    if username and username in known["usernames"]:
        return known["usernames"][username]

    # 3. нормализованный телефон
    phone = normalize_phone(sender.get("phone") or "")
    if phone and phone in known["phones"]:
        return known["phones"][phone]

    # 4. имя (последний шанс)
    sname = str(sender.get("name") or "").strip().lower()
    if sname and len(sname) > 3 and sname in known["names"]:
        return known["names"][sname]

    return None


# ---------------------------------------------------------------------------
# Обработка события
# ---------------------------------------------------------------------------
def process_event(evt, known):
    p = evt.get("payload", {})
    kind = evt.get("kind", "message")

    # Исходящие (из gateway /send) → единая история коммуникаций (20_Outbox/)
    if kind == "outgoing":
        save_outgoing(p, known)
        return

    if kind == "status":
        print(f"📬 status: outbox#{p.get('outbox_id')} → {p.get('status')}")
        return

    sender = p.get("from", {})
    chat = p.get("chat", {})
    text = p.get("text", "")

    client_name = match_sender(sender, known)
    sender_name = sender.get("name", "Без имени")
    sender_username = (sender.get("username") or "").lower().lstrip("@")
    sender_phone = sender.get("phone", "")
    sender_id = sender.get("id", "")

    is_ticket = text.lower().startswith("/ticket") or text.lower().startswith("#тикет")

    chat_id = str(chat.get("id") or "")
    bound_client = known.get("chats", {}).get(chat_id)
    # Привязанные группы (tg_chats) слушаем полностью; чужие — только упоминания
    if p.get("is_private"):
        if is_ticket:
            create_ticket(client_name, sender_name, sender_id, text)
        elif client_name:
            # ИЗВЕСТНЫЙ клиент → inbox с привязкой
            save_to_inbox(client_name, sender_name, text, p.get("id"), chat.get("id"), "Private Chat",
                          username=sender_username, phone=sender_phone, tg_id=sender_id)
        else:
            # Незнакомец → инбокс с меткой unmatched: лид или спам решит
            # 15-минутный разбор по тексту (см. Inbound_Pipeline «Лиды и спам»)
            save_to_inbox(None, sender_name, text, p.get("id"), chat.get("id"), "Private Chat",
                          username=sender_username, phone=sender_phone, tg_id=sender_id)
            fname_ts = time.strftime("%Y-%m-%d_%H-%M")
            fpath = os.path.join(INBOX_DIR, f"tg_{fname_ts}_Private_Chat.md")
            try:
                c = guard_open(fpath, "r", encoding="utf-8").read()
                c = c.replace('client: "[[]]"', 'unmatched: true', 1)
                guard_open(fpath, "w", encoding="utf-8").write(c)
            except Exception:
                pass
    elif p.get("is_group") and (p.get("mentioned") or bound_client):
        chat_title = chat.get("title", "Group")
        client_name = bound_client or client_name
        save_to_inbox(client_name, sender_name, text, p.get("id"), chat.get("id"), chat_title,
                      username=sender_username, phone=sender_phone, tg_id=sender_id)


def q(s):
    """Экранирует строку для YAML (в кавычках)."""
    return f'"{str(s or "").replace(chr(34), "")}"'


def save_outgoing(p, known):
    """Исходящее сообщение (gateway /send) → 20_Outbox/ — единая история ленты."""
    os.makedirs(OUTBOX_DIR, exist_ok=True)
    chat_id = str(p.get("chat_id") or "")
    client_name = known.get("chats", {}).get(chat_id) or ""
    author = p.get("author", "evgeny") or "evgeny"
    text = p.get("text", "")
    ts = time.strftime("%Y-%m-%d_%H-%M")
    safe = re.sub(r"[^\w\-]", "_", str(chat_id))[:30]
    fname = f"out_tg_{ts}_{safe}.md"
    content = f"""---
type: outgoing
channel: telegram
source: telegram-gateway
author: {author}
chat_id: {q(chat_id)}
client: "[[{client_name}]]"
outbox_id: {p.get("outbox_id", 0)}
date: {time.strftime("%Y-%m-%d %H:%M:%S")}
---
# OUT → TG {chat_id} ({author})

{text}
"""
    path = os.path.join(OUTBOX_DIR, fname)
    n = 1
    while os.path.exists(path):
        path = os.path.join(OUTBOX_DIR, fname.replace(".md", f"_{n}.md"))
        n += 1
    with guard_open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"📤 outbox-history ← tg {chat_id} ({author}): {text[:50]}")


def save_to_inbox(client_name, sender_name, text, msg_id, chat_id, chat_title,
                  username="", phone="", tg_id=""):
    """Сообщение известного клиента → 20_Inbox/."""
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y-%m-%d_%H-%M")
    safe = re.sub(r"[^\w\-]", "_", chat_title or "chat")[:40]
    fname = f"tg_{ts}_{safe}.md"
    content = f"""---
created: {time.strftime("%Y-%m-%d")}
source: telegram-gateway
sender: {q(sender_name)}
chat_id: {q(chat_id)}
msg_id: {msg_id or 0}
client: "[[{client_name or ''}]]"
tg_id: {q(tg_id)}
username: {q(username)}
phone: {q(phone)}
---
# TG: {sender_name} ({chat_title})

{text}
"""
    (INBOX_DIR / fname).write_text(content, encoding="utf-8")
    print(f"📥 inbox ← {sender_name} → {client_name}: {text[:50]}")

    try:
        from hub_push import send_event
        send_event(
            "new_tg_msg",
            f"TG: {sender_name} → {client_name or chat_title}",
            dedup_key=f"tg-{chat_id}-{msg_id}",
            payload={"sender": sender_name, "client": client_name, "chat": chat_title,
                     "preview": (text or "")[:120], "username": username},
            push={"title": f"💬 {sender_name}", "body": (text or "")[:80], "channel": "messages"},
        )
    except Exception:
        pass


def create_lead(name, username, phone, tg_id, text):
    """Новый контакт → лид в 15_Leads/."""
    LEADS_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w\-]", "_", name or "lead")[:30]
    fname = f"tg_lead_{time.strftime('%Y-%m-%d_%H-%M')}_{safe}.md"
    content = f"""---
created: {time.strftime("%Y-%m-%d")}
source: telegram-gateway
status: new
name: {q(name)}
telegram: {q('@' + username if username else '')}
phone: {q(phone)}
tg_id: {q(tg_id)}
---
# Лид: {name}

{text}
"""
    (LEADS_DIR / fname).write_text(content, encoding="utf-8")
    print(f"🆕 лид ← {name} (@{username}): {text[:50]}")

    try:
        from hub_push import send_event
        send_event(
            "new_tg_msg",
            f"Новый TG-лид: {name}",
            dedup_key=f"lead-{tg_id}-{int(time.time())}",
            payload={"sender": name, "lead": True, "username": username,
                     "preview": (text or "")[:120]},
            push={"title": f"🆕 Лид: {name}", "body": (text or "")[:80], "channel": "messages"},
        )
    except Exception:
        pass


def create_ticket(client_name, sender_name, tg_id, text):
    """Тикет → 45_Tickets/."""
    TICKETS_DIR.mkdir(parents=True, exist_ok=True)
    tid = uuid.uuid4().hex[:6]
    fname = f"ticket-{tid}.md"
    content = f"""---
created: {time.strftime("%Y-%m-%d")}
status: open
client: "[[{client_name or ''}]]"
source: telegram-gateway
sender: {q(sender_name)}
tg_id: {q(tg_id)}
priority: normal
---
# Тикет {tid} — {client_name or sender_name}

{text}
"""
    (TICKETS_DIR / fname).write_text(content, encoding="utf-8")
    print(f"🎫 тикет {tid} ← {sender_name} ({client_name or 'неизвестный'})")

    try:
        from hub_push import send_event
        send_event(
            "new_tg_msg",
            f"TG-тикет {tid}: {client_name or sender_name}",
            dedup_key=f"ticket-{tid}",
            payload={"sender": sender_name, "client": client_name,
                     "preview": (text or "")[:120]},
            push={"title": f"🎫 Тикет: {client_name or sender_name}", "body": (text or "")[:80],
                  "channel": "messages"},
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Главный цикл (long-poll + курсор)
# ---------------------------------------------------------------------------
def main():
    print(f"🚀 TG-Gateway client: {GATEWAY_URL}")

    if not GATEWAY_TOKEN:
        print("⚠️  TG_GATEWAY_TOKEN не задан — запросы пойдут без авторизации")

    h = gateway_get("/health")
    if not h:
        print("❌ Gateway недоступен. Проверьте TG_GATEWAY_URL и TLS.")
        sys.exit(1)
    print(f"✅ Gateway: {h.get('events', 0)} events, last_seq={h.get('last_seq', 0)}")

    # Восстанавливаем курсор (переживает перезапуск ПК)
    last_seq = load_cursor()
    if last_seq > 0:
        print(f"📍 Курсор восстановлен: last_seq={last_seq} (без дубликатов)")
    else:
        # Первый запуск — ставим курсор на текущую позицию, чтобы не выгрузить историю
        last_seq = h.get("last_seq", 0)
        save_cursor(last_seq)
        print(f"📍 Первый запуск — курсор = {last_seq} (история пропущена)")

    known = load_clients()
    reload_counter = 0

    print("🎧 Опрашиваю gateway (long-poll, wait=25s)...")
    while True:
        try:
            data = gateway_get(f"/events?after={last_seq}&limit=100&wait=25")
            if not data:
                time.sleep(POLL_INTERVAL)
                continue

            events = data.get("events", [])
            if events:
                for evt in events:
                    seq = evt.get("seq", 0)
                    if seq > last_seq:
                        try:
                            process_event(evt, known)
                            last_seq = seq
                        except Exception as e:
                            # Dead-letter: событие НЕ теряем молча — сохраняем для восстановления
                            print(f"❌ process_event seq={seq}: {e}")
                            try:
                                dl_path = os.path.join(BASE, "logs", "poller_failed_events.jsonl")
                                os.makedirs(os.path.dirname(dl_path), exist_ok=True)
                                with guard_open(dl_path, "a", encoding="utf-8") as dl:
                                    dl.write(json.dumps({"seq": seq, "error": str(e),
                                                         "event": evt, "ts": time.strftime("%Y-%m-%d %H:%M:%S")},
                                                        ensure_ascii=False) + "\n")
                            except Exception:
                                pass
                            last_seq = seq
                save_cursor(last_seq)
                # Подтверждаем забор — gateway удаляет ПДн из буфера на VPS (152-ФЗ)
                gateway_post("/events/ack", {"last_seq": last_seq})

            reload_counter += 1
            if reload_counter % 20 == 0:
                known = load_clients()
        except KeyboardInterrupt:
            print("\n👋 Остановка...")
            save_cursor(last_seq)
            break
        except Exception as e:
            print(f"❌ main loop: {e}")
            time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
