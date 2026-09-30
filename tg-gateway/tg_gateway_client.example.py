"""
tg_gateway_client.py — клиент локальной CRM к TG-Gateway (РАБОТАЕТ В РФ).

Заменяет сломанный tg_listener.py. Вместо прямого коннекта к Telegram
(заблокирован РКН) — опрашивает gateway на зарубежном VPS через HTTPS.
Исходящие запросы на 8443/443 проходят белые списки мобильного провайдера.

Логика (переиспользует вашу из tg_listener.py):
  - Новое сообщение от известного клиента → сохраняет в 20_Inbox/
  - Сообщение от незнакомца → создаёт лид в 15_Leads/
  - /ticket или #тикет → создаёт тикет в 45_Tickets/
  - Исходящий ответ из CRM → POST /send на gateway

Запуск:
    python3 scripts/tg_gateway_client.py

Настройка в .env:
    TG_GATEWAY_URL=https://VPS_IP:8443
    TG_GATEWAY_TOKEN=<GATEWAY_TOKEN с VPS>
"""
from sec_guard import guard_urlopen

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

# Загружаем .env из vault
try:
    from dotenv import load_dotenv
    load_dotenv(BASE / ".env")
    GATEWAY_URL = os.getenv("TG_GATEWAY_URL", GATEWAY_URL).rstrip("/")
    GATEWAY_TOKEN = os.getenv("TG_GATEWAY_TOKEN", GATEWAY_TOKEN)
except ImportError:
    pass

INBOX_DIR = BASE / "20_Inbox"
LEADS_DIR = BASE / "15_Leads"
TICKETS_DIR = BASE / "45_Tickets"
CLIENTS_DIR = BASE / "10_Clients"

# SSL: игнорируем проверку self-signed сертификата (на gateway он свой)
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE


# ---------------------------------------------------------------------------
# HTTP к gateway
# ---------------------------------------------------------------------------
def gateway_get(path):
    url = f"{GATEWAY_URL}{path}"
    req = urllib.request.Request(url, method="GET")
    if GATEWAY_TOKEN:
        req.add_header("Authorization", f"Bearer {GATEWAY_TOKEN}")
    try:
        with guard_urlopen(req, timeout=30, context=_SSL_CTX) as resp:
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
        print(f"❌ gateway POST {path}: {e}")
        return None


# ---------------------------------------------------------------------------
# Загрузка известных клиентов (как в tg_listener.py)
# ---------------------------------------------------------------------------
def load_clients():
    """Возвращает {tg_identifier: client_name} из frontmatter карточек."""
    import yaml
    clients = {}
    for f in CLIENTS_DIR.glob("*.md"):
        try:
            content = f.read_text(encoding="utf-8")
            m = re.search(r"^\s*---\n(.*?)\n---", content, re.DOTALL)
            if not m:
                continue
            meta = yaml.safe_load(m.group(1)) or {}
            name = f.stem
            for key in ("telegram", "tg_username", "phone"):
                val = str(meta.get(key, "")).strip().lower().lstrip("@")
                if val:
                    clients[val] = name
        except Exception:
            pass
    return clients


# ---------------------------------------------------------------------------
# Обработка события (логика из вашего tg_listener.py)
# ---------------------------------------------------------------------------
def process_event(evt, known_clients):
    """Обрабатывает одно событие из gateway."""
    if evt.get("kind") == "status":
        # Статус доставки исходящего — логируем, можно обновить счётчик
        p = evt.get("payload", {})
        print(f"📬 status: outbox#{p.get('outbox_id')} → {p.get('status')}")
        return

    p = evt.get("payload", {})
    sender = p.get("from", {})
    chat = p.get("chat", {})
    text = p.get("text", "")

    sender_name = sender.get("name", "Без имени")
    sender_username = sender.get("username", "").lower()
    sender_phone = sender.get("phone", "")
    sender_id = sender.get("id", "")

    # Мэтчинг с известными клиентами
    client_name = None
    for tg_ident, cname in known_clients.items():
        if tg_ident in (sender_username, sender_phone, sender_id, sender_name.lower()):
            client_name = cname
            break

    is_ticket = text.lower().startswith("/ticket") or text.lower().startswith("#тикет")

    if p.get("is_private"):
        if is_ticket:
            create_ticket(client_name, sender_name, sender_id, text)
        elif client_name:
            save_to_inbox(client_name, sender_name, text, p.get("id"), chat.get("id"), "Private Chat")
        else:
            create_lead(sender_name, sender_username, sender_phone, sender_id, text)
    elif p.get("mentioned"):
        chat_title = chat.get("title", "Group")
        save_to_inbox(client_name, sender_name, text, p.get("id"), chat.get("id"), chat_title)


def save_to_inbox(client_name, sender_name, text, msg_id, chat_id, chat_title):
    """Сохраняет сообщение в 20_Inbox/ (как tg_listener.py)."""
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y-%m-%d_%H-%M")
    safe = re.sub(r"[^\w\-]", "_", chat_title or "chat")[:40]
    fname = f"tg_{ts}_{safe}.md"
    content = f"""---
created: {time.strftime("%Y-%m-%d")}
source: telegram-gateway
sender: "{sender_name}"
chat_id: "{chat_id}"
msg_id: {msg_id or 0}
client: "[[{client_name or ''}]]"
---
# TG: {sender_name} ({chat_title})

{text}
"""
    (INBOX_DIR / fname).write_text(content, encoding="utf-8")
    print(f"📥 inbox ← {sender_name} ({client_name or 'неизвестный'}): {text[:50]}")


def create_lead(name, username, phone, tg_id, text):
    """Создаёт лид в 15_Leads/."""
    LEADS_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w\-]", "_", name or "lead")[:30]
    fname = f"tg_lead_{time.strftime('%Y-%m-%d_%H-%M')}_{safe}.md"
    content = f"""---
created: {time.strftime("%Y-%m-%d")}
source: telegram-gateway
status: new
name: "{name}"
telegram: "@{username}"
phone: "{phone}"
tg_id: "{tg_id}"
---
# Лид: {name}

{text}
"""
    (LEADS_DIR / fname).write_text(content, encoding="utf-8")
    print(f"🆕 лид ← {name} (@{username}): {text[:50]}")


def create_ticket(client_name, sender_name, tg_id, text):
    """Создаёт тикет в 45_Tickets/."""
    TICKETS_DIR.mkdir(parents=True, exist_ok=True)
    tid = uuid.uuid4().hex[:6]
    fname = f"ticket-{tid}.md"
    content = f"""---
created: {time.strftime("%Y-%m-%d")}
status: open
client: "[[{client_name or ''}]]"
source: telegram-gateway
sender: "{sender_name}"
tg_id: "{tg_id}"
priority: normal
---
# Тикет {tid} — {client_name or sender_name}

{text}
"""
    (TICKETS_DIR / fname).write_text(content, encoding="utf-8")
    print(f"🎫 тикет {tid} ← {sender_name} ({client_name or 'неизвестный'})")


# ---------------------------------------------------------------------------
# Главный цикл опроса (long-poll)
# ---------------------------------------------------------------------------
def main():
    print(f"🚀 TG-Gateway client: {GATEWAY_URL}")
    print(f"   Inbox → {INBOX_DIR}")

    if not GATEWAY_TOKEN:
        print("⚠️  TG_GATEWAY_TOKEN не задан — запросы пойдут без авторизации")

    # Проверка связи с gateway
    h = gateway_get("/health")
    if not h:
        print("❌ Gateway недоступен. Проверьте TG_GATEWAY_URL и TLS.")
        sys.exit(1)
    print(f"✅ Gateway: {h.get('events', 0)} events, last_seq={h.get('last_seq', 0)}")

    last_seq = 0
    # Перегружаем клиентов периодически (раз в N итераций)
    known_clients = load_clients()
    reload_counter = 0

    print("🎧 Опрашиваю gateway (long-poll, wait=25s)...")
    while True:
        try:
            data = gateway_get(f"/events?after={last_seq}&limit=100&wait=25")
            if not data:
                time.sleep(POLL_INTERVAL)
                continue

            events = data.get("events", [])
            for evt in events:
                seq = evt.get("seq", 0)
                if seq > last_seq:
                    last_seq = seq
                try:
                    process_event(evt, known_clients)
                except Exception as e:
                    print(f"❌ process_event seq={seq}: {e}")

            # Периодически перечитываем клиентов
            reload_counter += 1
            if reload_counter % 20 == 0:
                known_clients = load_clients()
        except KeyboardInterrupt:
            print("\n👋 Остановка...")
            break
        except Exception as e:
            print(f"❌ main loop: {e}")
            time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
