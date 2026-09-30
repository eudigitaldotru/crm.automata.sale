"""
userbot.py — Telegram Userbot для TG-Gateway (крутится на VPS).

Слушает входящие через Telethon (как ваш tg_listener.py), нормализует события
и кладёт в gateway.py (через HTTP /internal/event). Также забирает исходящие
из outbox gateway и отправляет их в Telegram.

ВАЖНО — правила выживания аккаунта (читайте перед запуском):
  - Один номер = один постоянный IP (этот VPS). Прыжки IP → быстрый бан.
  - Первые 2 недели: не более 20-30 исходящих в сутки, только ответы на входящие.
  - НИКОГДА не пишите первым тем, кто вам не писал.
  - .session-файл = полный доступ к аккаунту. Не коммитьте, шифруйте бэкап.

Авторизация: при первом запуске спросит код из SMS/Telegram. Сессия
сохранится в gateway_session.session — при последующих запусках код не нужен.
"""
from sec_guard import guard_urlopen

import os
import sys
import re
import json
import time
import asyncio
import hashlib
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

# Загружаем .env из папки скрипта (для ручного запуска вне systemd)
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

from telethon import TelegramClient, events
from telethon.tl.custom import Message

# --- КОНФИГУРАЦИЯ ---
API_ID = int(os.getenv("TG_API_ID", "0") or "0")
API_HASH = os.getenv("TG_API_HASH", "")
SESSION_FILE = os.getenv("TG_SESSION", "gateway_session")
# URL gateway (обычно http://localhost:8443, т.к. userbot и gateway на одном VPS)
GATEWAY_URL = os.getenv("GATEWAY_URL", "http://localhost:8443").rstrip("/")
GATEWAY_TOKEN = os.getenv("GATEWAY_TOKEN", "")
# Номер телефона аккаунта-менеджера (для автоавторизации без запроса при перезапуске).
# При первом старте Telethon спросит код из SMS/Telegram. После успешной авторизации
# .session сохранится и телефон больше не потребуется.
PHONE = os.getenv("TG_PHONE", "")

# Маппинг channel_id: кто слушает. 1 = личный аккаунт менеджера.
CHANNEL_ID = int(os.getenv("USERBOT_CHANNEL_ID", "1"))

if not API_ID or not API_HASH:
    print("❌ Задайте TG_API_ID и TG_API_HASH в .env")
    sys.exit(1)


# ---------------------------------------------------------------------------
# HTTP-клиент к gateway (urllib, без лишних зависимостей)
# ---------------------------------------------------------------------------
def _gateway_call(method: str, path: str, body: dict = None):
    url = f"{GATEWAY_URL}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if GATEWAY_TOKEN:
        req.add_header("Authorization", f"Bearer {GATEWAY_TOKEN}")
    try:
        with guard_urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"❌ gateway {method} {path} → HTTP {e.code}: {e.read().decode()[:200]}")
        return None
    except Exception as e:
        print(f"❌ gateway {method} {path} → {e}")
        return None


def put_event(chat_id: str, message: dict, dedup_key: str, kind: str = "message"):
    """Кладёт нормализованное событие в gateway."""
    payload = {
        "channel_id": CHANNEL_ID,
        "dedup_key": dedup_key,
        "chat_id": chat_id,
        "kind": kind,
        "payload": message,
    }
    return _gateway_call("POST", "/internal/event", payload)


# ---------------------------------------------------------------------------
# Telethon клиент
# ---------------------------------------------------------------------------
client = TelegramClient(SESSION_FILE, API_ID, API_HASH,
                        connection_retries=None, retry_delay=5,
                        request_retries=3)


def _safe(val, default=""):
    return str(val) if val is not None else default


@client.on(events.NewMessage(incoming=True))
async def on_new_message(event):
    """Нормализуем входящее сообщение и кладём в gateway."""
    try:
        sender = await event.get_sender()
        chat = await event.get_chat()

        sender_name = " ".join(filter(None, [
            _safe(getattr(sender, "first_name", None)),
            _safe(getattr(sender, "last_name", None)),
        ])).strip() or _safe(getattr(sender, "title", None)) or "Без имени"

        message = {
            "id": event.id,
            "date": event.date.isoformat() if event.date else None,
            "text": event.raw_text or "",
            "reply_to": event.reply_to_msg_id if event.reply_to_msg_id else None,
            "is_private": event.is_private,
            "is_group": bool(event.is_group or event.is_channel),
            "mentioned": bool(getattr(event, "mentioned", False)),
            "chat": {
                "id": _safe(event.chat_id),
                "title": _safe(getattr(chat, "title", None)) or sender_name,
            },
            "from": {
                "id": _safe(getattr(sender, "id", None)),
                "username": _safe(getattr(sender, "username", None)).lower(),
                "name": sender_name,
                "phone": _safe(getattr(sender, "phone", None)),
            },
        }

        # Дедуп-ключ: user:<peer>:<msg_id> — Telegram может прислать апдейт дважды
        dedup = f"user:{event.chat_id}:{event.id}"
        put_event(str(event.chat_id), message, dedup_key=dedup)

        preview = message["text"][:60].replace("\n", " ")
        print(f"📩 [{message['chat']['title']}] {sender_name}: {preview}")
    except Exception as e:
        print(f"❌ on_new_message: {e}")


# ---------------------------------------------------------------------------
# Воркер отправки: забирает outbox из gateway и шлёт в Telegram
# ---------------------------------------------------------------------------
SEND_POLL_INTERVAL = 2  # сек


async def outbox_sender_loop():
    """Периодически забирает pending-сообщения из gateway и отправляет."""
    print("📤 Outbox-sender loop started.")
    while True:
        try:
            resp = _gateway_call("GET", "/internal/outbox/pending?limit=20")
            if resp and resp.get("items"):
                for item in resp["items"]:
                    await _send_one(item)
        except Exception as e:
            print(f"❌ outbox_sender_loop: {e}")
        await asyncio.sleep(SEND_POLL_INTERVAL)


async def _send_one(item):
    """Отправляет одно сообщение из outbox и сообщает результат в gateway."""
    outbox_id = item["id"]
    chat_id = item["chat_id"]
    text = item["text"] or ""
    reply_to = item.get("reply_to")

    # Защита от пустых сообщений
    if not text.strip():
        _gateway_call("POST", f"/internal/outbox/{outbox_id}/result",
                      {"ok": False, "error": "empty text"})
        return

    try:
        # Резолвим получателя: chat_id может быть числом, @username или телефоном (+7XXXXXXXXXX).
        target = chat_id
        if isinstance(chat_id, str) and chat_id.lstrip("-").isdigit():
            target = int(chat_id)
        elif isinstance(chat_id, str) and (chat_id.startswith("+") or chat_id.startswith("7") or chat_id.startswith("8")):
            digits = re.sub(r"\D", "", chat_id)
            if len(digits) == 11 and digits.startswith("8"):
                digits = "7" + digits[1:]
            if not digits.startswith("7"):
                digits = "7" + digits
            target = "+" + digits
        elif isinstance(chat_id, str) and not chat_id.startswith("@"):
            target = "@" + chat_id if chat_id else chat_id

        entity = await client.get_entity(target)

        # Если есть PDF-вложение — отправляем файл + текст как подпись
        pdf_b64 = item.get("pdf_base64")
        pdf_fname = item.get("pdf_filename") or "document.pdf"
        if pdf_b64:
            import base64 as _b64
            import tempfile
            pdf_bytes = _b64.b64decode(pdf_b64)
            # Сохраняем во временный файл (Telethon send_file требует путь или bytes).
            # Имя и расширение — из pdf_filename: xlsx уйдёт как xlsx, pdf как pdf.
            import os as _os, shutil as _shutil
            _safe = "".join(ch for ch in (_os.path.basename(pdf_fname) or "document.pdf")
                            if ch not in "/\\\0")
            if not _os.path.splitext(_safe)[1]:
                _safe += ".pdf"
            _tmpdir = tempfile.mkdtemp(prefix="tgw_")
            _fpath = _os.path.join(_tmpdir, _safe)
            with open(_fpath, "wb") as _f:
                _f.write(pdf_bytes)
            try:
                msg = await client.send_file(entity, _fpath,
                                            caption=text[:1024] if text else "",
                                            reply_to=reply_to)
            finally:
                _shutil.rmtree(_tmpdir, ignore_errors=True)
        else:
            msg = await client.send_message(entity, text, reply_to=reply_to)
        tg_mid = msg.id
        print(f"✅ → chat {chat_id}: {text[:50]}  (tg_id={tg_mid})")
        _gateway_call("POST", f"/internal/outbox/{outbox_id}/result",
                      {"ok": True, "tg_message_id": tg_mid})

        # Мягкий rate-limit: пауза между отправками
        await asyncio.sleep(1)
    except Exception as e:
        err = str(e)[:300]
        print(f"❌ → chat {chat_id}: {err}")
        _gateway_call("POST", f"/internal/outbox/{outbox_id}/result",
                      {"ok": False, "error": err})


# ---------------------------------------------------------------------------
# Старт
# ---------------------------------------------------------------------------
async def main():
    print("🚀 Starting userbot...")
    # phone передаём, чтобы при наличии валидной сессии не запрашивался повторно
    try:
        await client.start(phone=PHONE if PHONE else None)
    except Exception as e:
        err = str(e)
        if "FloodWait" in err:
            import re as _re
            m = _re.search(r"wait of (\d+) seconds", err)
            secs = int(m.group(1)) if m else 0
            hours, rem = divmod(secs, 3600)
            mins = rem // 60
            print(f"⏳ FloodWait: Telegram требует подождать {hours}ч {mins}м перед запросом кода.")
            print("   НЕ перезапускайте скрипт до истечения этого срока — каждая попытка продлевает блокировку!")
            print("   После истечения: запустите вручную (python userbot.py), введите код из Telegram.")
            sys.exit(2)  # код 2 = ждать, systemd не должен спамить рестартами
        raise
    me = await client.get_me()
    print(f"✅ Авторизован как: {_safe(getattr(me,'first_name',None))} "
          f"@{_safe(getattr(me,'username',None))} (id={me.id})")
    print(f"   Канал: channel_id={CHANNEL_ID} → gateway {GATEWAY_URL}")

    # Догоняем пропущенные апдейты (инцидент 11.09 10:06: после длинного разрыва
    # Telegram не досылает сообщения — catch_up делает getDifference)
    try:
        await client.catch_up()
        print("✅ catch_up: пропущенные апдейты дозапрошены")
    except Exception as e:
        print(f"⚠️ catch_up: {e}")

    # Запускаем воркер отправки параллельно со слушателем событий
    asyncio.create_task(outbox_sender_loop())
    # Запускаем heartbeat: каждые 30с пингуем gateway (для индикатора "TG жив")
    asyncio.create_task(heartbeat_loop(me.id, _safe(getattr(me, 'username', None))))

    print("🎧 Слушаю входящие... (Ctrl+C для остановки)")
    await client.run_until_disconnected()


async def heartbeat_loop(me_id, me_username):
    """Каждые 30с шлёт ping на gateway — фронтенд CRM видит что userbot жив."""
    while True:
        try:
            _gateway_call("POST", "/internal/userbot-ping", {
                "me_id": str(me_id),
                "me_name": me_username or "",
            })
        except Exception:
            pass
        await asyncio.sleep(30)


if __name__ == "__main__":
    try:
        client.loop.run_until_complete(main())
    except KeyboardInterrupt:
        print("\n👋 Остановка...")
