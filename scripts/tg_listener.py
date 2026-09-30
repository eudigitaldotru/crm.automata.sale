
from sec_guard import guard_open
import os
import sys
import yaml
import re
import datetime
import asyncio
from dotenv import load_dotenv
from telethon import TelegramClient, events

# --- FORCE DISABLE PROXY (Common fix for local network issues) ---
for key in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY']:
    os.environ.pop(key, None)

# --- CONFIGURATION ---
BASE_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLIENTS_DIR = os.path.join(BASE_PATH, "10_Clients")
INBOX_DIR = os.path.join(BASE_PATH, "20_Inbox")
import imaplib
import email
from email.header import decode_header
from mail_utils import send_mail, EMAIL_USER

EMAIL_PASS = os.getenv("EMAIL_PASS")
IMAP_SERVER = os.getenv("EMAIL_IMAP_HOST", "imap.timeweb.ru")

dotenv_path = os.path.join(BASE_PATH, ".env")
load_dotenv(dotenv_path)

API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")

if not API_ID or not API_HASH:
    print("❌ Error: API_ID or API_HASH not found in .env file.")
    sys.exit(1)

def parse_frontmatter(file_path):
    try:
        with guard_open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        match = re.search(r'^\s*---\n(.*?)\n---', content, re.DOTALL)
        if match:
             return yaml.safe_load(match.group(1)), content
    except Exception as e:
        pass
    return {}, ""

def load_clients():
    """Loads all known clients and their Telegram IDs from the CRM."""
    clients = {}
    if not os.path.exists(CLIENTS_DIR):
        return clients
        
    for fname in os.listdir(CLIENTS_DIR):
        if not fname.endswith(".md"): continue
        file_path = os.path.join(CLIENTS_DIR, fname)
        client_name = fname.replace(".md", "")
        meta, content = parse_frontmatter(file_path)
        
        # Determine telegram ID/username
        client_tg = str(meta.get('telegram_id') or meta.get('telegram', '')).strip()
        
        # Fallback to searching the markdown body if not in frontmatter
        if not client_tg or client_tg.lower() == 'none' or client_tg == '':
            match = re.search(r'\*\*Telegram:\*\*\s*(.+)', content)
            if match:
                 client_tg = match.group(1).strip()
                 
        if client_tg and client_tg.lower() != 'none':
            # Remove @ symbol for usernames to match easily
            clean_tg = client_tg.replace('@', '').lower()
            clients[clean_tg] = client_name
            
    return clients

def sanitize_filename(name):
    return re.sub(r'[\\/*?:"<>|]', "", name)

def create_lead_from_tg(sender_name, username, phone, tg_id, text):
    if not os.path.exists(CLIENTS_DIR):
        os.makedirs(CLIENTS_DIR)
        
    safe_name = sanitize_filename(sender_name if sender_name else f"TG_Lead_{tg_id}")
    now = datetime.datetime.now()
    date_str = now.strftime("%Y-%m-%d %H:%M:%S")
    
    file_name = f"Лид_{safe_name}.md"
    file_path = os.path.join(CLIENTS_DIR, file_name)
    
    # If the lead already exists, just log to inbox
    if os.path.exists(file_path):
        save_to_inbox(f"Лид_{safe_name}", sender_name, text, 0, tg_id, "Private Chat", False)
        return
        
    frontmatter = f"""---
created: {now.strftime('%Y-%m-%d')}
modified: {now.strftime('%Y-%m-%d')}
tags: [client, lead]
lifecycle: prospect
support_type: none
support_plan: ""
hours_used_current_month: 0
company_name: "{safe_name}"
contact_name: "{safe_name}"
telegram: "{username or tg_id}"
telegram_id: "{tg_id}"
phone: "{phone}"
source: "telegram"
status: "new"
last_contact_at: "{date_str}"
rate: 3000
total_revenue: 0
invoice_amount: 0
---

# {safe_name} (TG Лид)

> **Жизненный цикл:** `= this.lifecycle` | **Тип:** `= this.support_type` | **План:** `= this.support_plan`

## 💬 Первое сообщение
{text}
"""
    try:
        with guard_open(file_path, "w", encoding="utf-8") as f:
            f.write(frontmatter)
        print(f"✅ Created NEW lead: {file_name}")
    except Exception as e:
        print(f"❌ Failed to create lead: {e}")

def save_to_inbox(client_name, sender_name, message_text, msg_id, chat_id, chat_title, is_group):
    """Creates a new Markdown file in the Inbox directory."""
    if not os.path.exists(INBOX_DIR):
        os.makedirs(INBOX_DIR)
        
    now = datetime.datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")
    
    # Filename format: TG_YYYY-MM-DD_SenderName.md
    safe_sender = sanitize_filename(sender_name if sender_name else "Unknown")
    file_name = f"TG_{date_str}_{safe_sender}.md"
    file_path = os.path.join(INBOX_DIR, file_name)
    
    # Form message link (works for supergroups/channels, sometimes fails for private, but good enough)
    msg_link = f"https://t.me/c/{str(chat_id).replace('-100', '')}/{msg_id}"
    
    client_tag = f'"[[{client_name}]]"' if client_name else '""'
    source_tag = "Группа/Чат" if is_group else "Личные Сообщения"
    
    frontmatter = f"""---
created: {date_str} {time_str}
tags:
  - inbox
  - telegram
client: {client_tag}
source: "{source_tag}"
sender: "{safe_sender}"
chat_title: "{chat_title}"
---

# 💬 Telegram: {safe_sender} ({time_str})

> **Источник:** {source_tag} {chat_title if is_group else ''}
> [➡️ Перейти к сообщению в Telegram]({msg_link})

---

{message_text}

---
"""
    try:
        # If file already exists (same minute from same sender), append to handle bursts
        if os.path.exists(file_path):
             with guard_open(file_path, "a", encoding="utf-8") as f:
                 f.write(f"\n**{time_str}**:\n{message_text}\n---\n")
        else:
             with guard_open(file_path, "w", encoding="utf-8") as f:
                 f.write(frontmatter)
        print(f"✅ Saved message from {safe_sender} to Inbox.")
        
        # --- DELTA CHAT REPLICATION ---
        subject = f"[TG] {safe_sender} ({client_name if client_name else 'Unknown Client'})"
        # Include hidden-ish metadata for reply routing
        body = f"Message from {safe_sender}:\n\n{message_text}\n\n---\n[REPLY_METADATA:tg_id={chat_id}]\nCreated in Inbox: {file_name}"
        if send_mail(EMAIL_USER, subject, body):
            print(f"📨 Forwarded message to Delta Chat ({EMAIL_USER})")
            
    except Exception as e:
        print(f"❌ Failed to save to Inbox or Forward: {e}")

def create_ticket(client_name, sender_name, tg_id, text):
    tickets_dir = os.path.join(BASE_PATH, "45_Tickets")
    os.makedirs(tickets_dir, exist_ok=True)
    
    import uuid
    ticket_id = f"ticket-{str(uuid.uuid4())[:6]}"
    now = datetime.datetime.now()
    deadline = now + datetime.timedelta(hours=4)
    
    clean_text = text.replace("/ticket", "").replace("#тикет", "").strip()
    
    safe_title = sanitize_filename(clean_text[:30].strip())
    if not safe_title:
        safe_title = "Новый_тикет"
        
    client_field = f'"[[{client_name}]]"' if client_name else f'"{sender_name}"'
    
    frontmatter = f"""---
id: {ticket_id}
created: {now.strftime('%Y-%m-%dT%H:%M:%S')}
client: {client_field}
title: "{safe_title}"
description: ""
status: open
priority: high
sla_hours: 4
sla_deadline: {deadline.strftime('%Y-%m-%dT%H:%M:%S')}
resolved_at: ""
time_spent_hours: ""
alert_sent: false
tags:
  - ticket
---
# Тикет: `= this.title`

> **Клиент:** `= this.client` | **Приоритет:** `= this.priority` | **Статус:** `= this.status`
> **SLA дедлайн:** `= this.sla_deadline`

## Описание проблемы
{clean_text}

## Решение

"""
    file_path = os.path.join(tickets_dir, f"{safe_title}_{ticket_id}.md")
    try:
        with guard_open(file_path, "w", encoding="utf-8") as f:
            f.write(frontmatter)
        print(f"✅ Created ticket: {safe_title}_{ticket_id}.md")
        return ticket_id
    except Exception as e:
        print(f"❌ Failed to create ticket: {e}")
        return None

async def main():
    print("⏳ Loading known clients...")
    KNOWN_CLIENTS = load_clients()
    print(f"✅ Loaded {len(KNOWN_CLIENTS)} clients with Telegram IDs.")
    
    session_dir = os.path.dirname(os.path.abspath(__file__))
    session_file = os.path.join(session_dir, 'invoice_session')
    
    client = TelegramClient(session_file, int(API_ID), API_HASH)

    async def mail_bridge_loop():
        """Periodic task to check email and forward to TG."""
        print("🛰️ Mail-to-TG Bridge loop started.")
        while True:
            try:
                await process_email_to_tg(client)
            except Exception as e:
                print(f"❌ Error in mail bridge loop: {e}")
            await asyncio.sleep(30)

    def fetch_and_delete_emails_sync():
        try:
            mail = imaplib.IMAP4_SSL(IMAP_SERVER)
            mail.login(EMAIL_USER, EMAIL_PASS)
            mail.select("inbox")
        except Exception as e:
            return []

        status, messages = mail.search(None, f'UNSEEN FROM "{EMAIL_USER}"')
        email_ids = messages[0].split()
        actions = []

        for email_id in email_ids:
            try:
                res, msg_data = mail.fetch(email_id, "(RFC822)")
                body = ""
                for response_part in msg_data:
                    if isinstance(response_part, tuple):
                        msg = email.message_from_bytes(response_part[1])
                        if msg.is_multipart():
                            for part in msg.walk():
                                if part.get_content_type() == "text/plain":
                                    try:
                                        body = part.get_payload(decode=True).decode()
                                        break
                                    except: pass
                        else:
                            body = msg.get_payload(decode=True).decode()

                match = re.search(r'\[REPLY_METADATA:tg_id=(-?\d+)\]', body)
                if match:
                    tg_chat_id = int(match.group(1))
                    clean_msg = body.split("---")[0].strip()
                    if not clean_msg:
                        clean_msg = body.split("\n\n")[0].strip()

                    actions.append((tg_chat_id, clean_msg))
                    mail.store(email_id, '+FLAGS', '\\Deleted')
                else:
                    mail.store(email_id, '+FLAGS', '\\Seen')
            except Exception as e:
                pass

        try:
            mail.expunge()
            mail.close()
            mail.logout()
        except: pass

        return actions

    async def process_email_to_tg(tg_client):
        # Run the blocking IMAP operations in a separate thread!
        actions = await asyncio.to_thread(fetch_and_delete_emails_sync)
        for tg_chat_id, clean_msg in actions:
            print(f"🚀 Forwarding reply from Delta Chat to TG ID {tg_chat_id}...")
            try:
                await tg_client.send_message(tg_chat_id, clean_msg)
            except Exception as e:
                print(f"❌ Failed to send message to {tg_chat_id}: {e}")
    
    @client.on(events.NewMessage)
    async def handler(event):
        print(f"📩 [NewMessage] Received from: {event.chat_id}")
        # Reload clients on every message to catch newly added/updated clients
        KNOWN_CLIENTS = load_clients()
        
        sender = await event.get_sender()
        chat = await event.get_chat()
        
        sender_name = getattr(sender, 'username', '')
        if not sender_name:
             sender_name = getattr(sender, 'first_name', '') + " " + getattr(sender, 'last_name', '')
        sender_name = sender_name.strip()
        
        sender_username = str(getattr(sender, 'username', '')).lower()
        sender_phone = str(getattr(sender, 'phone', ''))
        sender_id = str(getattr(sender, 'id', ''))
        
        # Try to match the sender with known clients
        client_name = None
        for tg_identifier, c_name in KNOWN_CLIENTS.items():
             if tg_identifier in (sender_username, sender_phone, sender_id):
                 client_name = c_name
                 break
                 
        is_ticket_cmd = event.text.lower().startswith('/ticket') or event.text.lower().startswith('#тикет')
                 
        if event.is_private:
             if is_ticket_cmd:
                 ticket_id = create_ticket(client_name, sender_name, sender_id, event.text)
                 if ticket_id:
                     await event.reply(f"✅ Тикет создан! ID: {ticket_id}. Мы свяжемся с вами по готовности.")
             elif client_name:
                 print(f"📩 [Private] Capturing message from {sender_name} ({client_name})...")
                 save_to_inbox(client_name, sender_name, event.text, event.id, event.chat_id, "Private Chat", False)
             else:
                 print(f"📩 [Private/New] Message from UNKNOWN contact {sender_name}...")
                 create_lead_from_tg(sender_name, sender_username, sender_phone, sender_id, event.text)
        elif event.is_group or event.is_channel:
             # Group Message - only capture if mentioned
             if is_ticket_cmd:
                 ticket_id = create_ticket(client_name, sender_name, sender_id, event.text)
                 if ticket_id:
                     await event.reply(f"✅ Тикет создан! ID: {ticket_id}.")
             elif event.mentioned:
                 chat_title = getattr(chat, 'title', 'Unknown Group')
                 print(f"🔔 [Mention] You were mentioned in {chat_title} by {sender_name}!")
                 save_to_inbox(client_name, sender_name, event.text, event.id, event.chat_id, chat_title, True)

    print("🚀 Telegram Listener started. Waiting for messages...")
    await client.start()
    
    # Mail bridge logic disabled temporarily to stop looping
    # asyncio.create_task(mail_bridge_loop())
    
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
