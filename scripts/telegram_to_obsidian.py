
from sec_guard import guard_open
import os
import asyncio
from datetime import datetime
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.tl.types import PeerUser, PeerChat, PeerChannel

# --- FORCE DISABLE PROXY ---
for key in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY']:
    os.environ.pop(key, None)

load_dotenv()

# CONFIG
API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
MY_USER_ID = int(os.getenv("MY_USER_ID", 0))

# Tracked Users: Load from ENV
TRACKED_USERS = [
    u.strip().lower()
    for u in os.getenv("TRACKED_USERS", "").split(",")
    if u.strip()
]

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INBOX_DIR = os.path.join(BASE_DIR, "20_Inbox")

userbot = TelegramClient(os.path.join(BASE_DIR, "telegram_userbot_session"), API_ID, API_HASH)

async def save_message_to_obsidian(event, reason):
    sender = await event.get_sender()
    sender_username = getattr(sender, "username", "Unknown") or "Unknown"
    sender_name = getattr(sender, "first_name", "") or getattr(sender, "title", "Unknown")
    
    chat = await event.get_chat()
    chat_title = getattr(chat, "title", "Private Chat")
    chat_username = getattr(chat, "username", None)
    
    # Generate Link
    link = ""
    if chat_username and event.message.id:
        link = f"https://t.me/{chat_username}/{event.message.id}"
    elif hasattr(event.message.peer_id, "channel_id"):
         link = f"https://t.me/c/{event.message.peer_id.channel_id}/{event.message.id}"
         
    text = event.message.raw_text or "[Media/Sticker]"
    
    timestamp = datetime.now()
    filename = f"{timestamp.strftime('%Y-%m-%d_%H-%M')}_Telegram_{sender_username}.md"
    filepath = os.path.join(INBOX_DIR, filename)
    
    content = f"""---
type: incoming
source: telegram
sender: "@{sender_username}"
sender_name: "{sender_name}"
chat: "{chat_title}"
date: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}
link: "{link}"
reason: "{reason}"
---
# Telegram from {sender_name} (@{sender_username})

**Chat**: {chat_title}
**Date**: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}
**Link**: [Open Message]({link})

---

{text}
"""
    try:
        with guard_open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"✅ Saved to: {filename}")
    except Exception as e:
        print(f"❌ Error saving file: {e}")

@userbot.on(events.NewMessage(incoming=True))
async def handler(event):
    if event.sender_id == MY_USER_ID:
        return

    try:
        sender = await event.get_sender()
        if not sender:
            return
            
        username = getattr(sender, "username", "")
        if username:
            username = username.lower()
            
        # Check Tracked Users
        if username in TRACKED_USERS:
            await save_message_to_obsidian(event, "tracked_user")
            return
            
        # Check Mentions (Optional, but good to have)
        if event.message.mentioned:
             # Double check if it's explicitly us
             # For now, just save if identified as mention by API
             await save_message_to_obsidian(event, "mention")
             return

    except Exception as e:
        print(f"Handler Error: {e}")

async def main():
    print("🚀 Starting Telegram -> Obsidian Listener...")
    print(f"📂 Saving to: {INBOX_DIR}")
    print(f"👀 Tracking: {TRACKED_USERS}")
    
    if not API_ID or not API_HASH:
        print("❌ Error: API_ID or API_HASH missing in .env")
        return

    await userbot.start()
    print("✅ Userbot connected listening...")
    await userbot.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
