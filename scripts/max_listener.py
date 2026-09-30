"""
max_listener.py — слушатель мессенджера MAX (Bot API long polling).

Забирает обновления (GET /updates, авторизация заголовком БЕЗ Bearer —
проверено боем в smm-autopilot) и складывает сообщения из привязанных
групп (max_chats в карточках клиентов) в 20_Inbox/max_*.md.

Правило конвейера: только «свои» чаты из .contact_index.json (by_chat_id);
сообщения чужих чатов и сообщения самого бота игнорируются.

Запуск потоком из monitoring_daemon.py или вручную:
    python3 scripts/max_listener.py
"""
from sec_guard import guard_urlopen

import json
import os
import re
import time
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
INBOX = BASE / "20_Inbox"
MARKER_FILE = Path(__file__).resolve().parent / ".max_marker"
INDEX_FILE = Path(__file__).resolve().parent / ".contact_index.json"

try:
    from dotenv import load_dotenv
    load_dotenv(BASE / ".env")
except ImportError:
    pass

TOKEN = os.getenv("MAX_BOT_TOKEN", "")
API = "https://botapi.max.ru"


def api_get(path):
    req = urllib.request.Request(f"{API}{path}", headers={"Authorization": TOKEN})
    with guard_urlopen(req, timeout=35) as r:
        return json.loads(r.read().decode())


def load_marker():
    try:
        return int(MARKER_FILE.read_text().strip() or 0)
    except Exception:
        return -1


def save_marker(m):
    MARKER_FILE.write_text(str(m))


def load_known():
    try:
        return json.loads(INDEX_FILE.read_text(encoding="utf-8")).get("by_chat_id", {})
    except Exception:
        return {}


def save_message(msg, known):
    sender = msg.get("sender") or {}
    recip = msg.get("recipient") or {}
    chat_id = str(recip.get("chat_id") or "")
    body = msg.get("body") or {}
    text = body.get("text", "") or ""
    mid = body.get("mid", "")

    # свои сообщения бота — не пишем (они уже в 20_Outbox через отправителя)
    if str(sender.get("user_id") or "") == str(sender.get("bot_id") or "x") or sender.get("type") == "bot":
        return False

    known_chat = known.get(chat_id)
    if not known_chat:
        # незнакомец: личное сообщение боту → инбокс с меткой unmatched
        # (решение лид/спам — за 15-минутным разбором); чужие группы — игнор
        client = ""
        chat_title = "MAX Private"
    else:
        client = known_chat["client"]
        chat_title = known_chat.get("chat_title") or chat_id
    unmatched = not known_chat
    sender_name = sender.get("name", "Без имени")
    ts = time.strftime("%Y-%m-%d_%H-%M")
    safe = re.sub(r"[^\w\-]", "_", chat_title)[:30]
    fname = f"max_{ts}_{safe}.md"
    path = INBOX / fname
    n = 1
    while path.exists():
        path = INBOX / fname.replace(".md", f"_{n}.md")
        n += 1
    path.write_text(f"""---
type: incoming
source: max-bot
channel: max
sender: "{sender_name}"
max_user_id: "{sender.get('user_id', '')}"
chat_id: "{chat_id}"
msg_id: "{mid}"
{("[[{client}]]" if client else "unmatched: true")}
date: {time.strftime("%Y-%m-%d %H:%M:%S")}
---
# MAX: {sender_name} ({chat_title})

{text if text else "(вложение/медиа)"}
""", encoding="utf-8")
    print(f"📥 max ← {sender_name} [{chat_title}] → {client}: {text[:50]}")

    try:
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from hub_push import send_event
        send_event(
            "new_max_msg",
            f"MAX: {sender_name} → {client}",
            dedup_key=f"max-{mid or chat_id + ts}",
            payload={"sender": sender_name, "client": client, "chat": chat_title,
                     "preview": (text or "")[:120]},
            push={"title": f"🟣 {sender_name}", "body": (text or "")[:80], "channel": "messages"},
        )
    except Exception:
        pass
    return True


def main():
    if not TOKEN:
        print("❌ MAX_BOT_TOKEN не задан в .env")
        return
    me = api_get("/me")
    print(f"✅ MAX-бот: {me.get('name', '?')} (id={me.get('user_id', me.get('bot_id', '?'))})")
    marker = load_marker()
    known = load_known()
    reload_n = 0
    print("🎧 Слушаю MAX /updates (long polling)...")
    while True:
        try:
            d = api_get(f"/updates?marker={marker}&timeout=25&types=MESSAGE_CREATED")
            marker = d.get("marker", marker)
            for u in d.get("updates", []):
                if u.get("update_type") == "message_created":
                    save_message(u.get("message", {}), known)
            save_marker(marker)
            reload_n += 1
            if reload_n % 60 == 0:
                known = load_known()
        except KeyboardInterrupt:
            print("\n👋 Остановка MAX-слушателя")
            break
        except Exception as e:
            print(f"❌ max updates: {e}")
            time.sleep(10)


if __name__ == "__main__":
    main()
