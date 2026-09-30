
from sec_guard import guard_open
import os
import sys
import yaml
import time
from datetime import datetime
import asyncio
from telethon import TelegramClient

BASE_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TICKETS_DIR = os.path.join(BASE_PATH, "45_Tickets")

# Setup Telegram Client for sending alerts
from dotenv import load_dotenv
load_dotenv(os.path.join(BASE_PATH, ".env"))

API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
ADMIN_TG_ID = os.getenv("ADMIN_TG_ID") # Set this in .env or hardcode if needed

if not API_ID or not API_HASH:
    print("❌ Error: API_ID or API_HASH not found in .env")
    sys.exit(1)

def parse_frontmatter(file_path):
    try:
        with guard_open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        import re
        match = re.search(r'^\s*---\n(.*?)\n---', content, re.DOTALL)
        if match:
             return yaml.safe_load(match.group(1)), content, match.span(1)
    except Exception as e:
        pass
    return {}, "", None

def update_frontmatter(file_path, new_meta, original_content, meta_span):
    try:
        new_yaml = yaml.dump(new_meta, allow_unicode=True, default_flow_style=False, sort_keys=False)
        start, end = meta_span
        new_content = original_content[:start] + new_yaml + original_content[end:]
        with guard_open(file_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        return True
    except Exception as e:
        print(f"Failed to update {file_path}: {e}")
        return False

async def check_slas():
    session_dir = os.path.dirname(os.path.abspath(__file__))
    session_file = os.path.join(session_dir, 'sla_session')
    client = TelegramClient(session_file, int(API_ID), API_HASH)
    
    await client.start()
    print("✅ SLA Timer started. Checking tickets...")
    
    # We send alerts to Saved Messages (me) if ADMIN_TG_ID is not set
    admin_id = int(ADMIN_TG_ID) if ADMIN_TG_ID else 'me'
    
    while True:
        if not os.path.exists(TICKETS_DIR):
            await asyncio.sleep(60)
            continue
            
        now = datetime.now()
        for fname in os.listdir(TICKETS_DIR):
            if not fname.endswith(".md"): continue
            if fname in ("_kanban_board.md",): continue
            
            file_path = os.path.join(TICKETS_DIR, fname)
            meta, content, span = parse_frontmatter(file_path)
            
            if not meta or meta.get("status") != "open":
                continue
                
            sla_deadline_str = meta.get("sla_deadline")
            alert_sent = meta.get("alert_sent", False)
            
            if sla_deadline_str and not alert_sent:
                try:
                    deadline = datetime.fromisoformat(sla_deadline_str.replace("Z", ""))
                    hours_remaining = (deadline - now).total_seconds() / 3600
                    
                    if hours_remaining <= 1:
                        # SLA is about to expire or expired!
                        urgency = "⚠️ СКОРО ИСТЕЧЕТ" if hours_remaining > 0 else "🚨 ПРОСРОЧЕН"
                        msg = (
                            f"{urgency} SLA по тикету!\n\n"
                            f"**Тикет:** {meta.get('title', fname)}\n"
                            f"**Клиент:** {meta.get('client', 'Неизвестен')}\n"
                            f"**Дедлайн:** {deadline.strftime('%H:%M %d.%m.%Y')}\n"
                            f"**Осталось:** {round(hours_remaining, 1)} часов"
                        )
                        await client.send_message(admin_id, msg)
                        print(f"Sent SLA alert for {fname}")
                        
                        # Mark as sent
                        meta["alert_sent"] = True
                        update_frontmatter(file_path, meta, content, span)
                        
                except Exception as e:
                    print(f"Error processing SLA for {fname}: {e}")
                    
        # Check every 5 minutes
        await asyncio.sleep(300)

if __name__ == "__main__":
    asyncio.run(check_slas())
