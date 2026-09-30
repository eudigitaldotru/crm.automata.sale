import os
import sys
import yaml
import re
import datetime
import asyncio
from dotenv import load_dotenv
from telethon import TelegramClient

# --- FORCE DISABLE PROXY (Common fix for local network issues) ---
for key in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY']:
    os.environ.pop(key, None)

BASE_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FINANCES_DIR = os.path.join(BASE_PATH, "60_PersonalFinances")

dotenv_path = os.path.join(BASE_PATH, ".env")
load_dotenv(dotenv_path)

API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")

if not API_ID or not API_HASH:
    print("No API_ID or API_HASH in .env, skipping reminders")
    sys.exit(0)

async def check_reminders():
    if not os.path.exists(FINANCES_DIR):
        print("Finances dir not found")
        return

    today = datetime.date.today()
    
    messages = []
    
    for fname in os.listdir(FINANCES_DIR):
        if not fname.endswith(".md"): continue
        path = os.path.join(FINANCES_DIR, fname)
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        match = re.search(r'^\s*---\n(.*?)\n---', content, re.DOTALL)
        if not match: continue
        
        meta = yaml.safe_load(match.group(1))
        if not meta or 'due_day' not in meta or 'notify_days_before' not in meta:
            continue
            
        due_day = int(meta['due_day'])
        notify_days = int(meta['notify_days_before'])
        
        try:
            due_date = today.replace(day=due_day)
        except ValueError:
            if today.month == 2:
                due_date = today.replace(day=28)
            else:
                due_date = today.replace(day=30)
                
        if due_date < today:
            month = today.month + 1
            year = today.year
            if month > 12:
                month = 1
                year += 1
            try:
                due_date = datetime.date(year, month, due_day)
            except ValueError:
                due_date = datetime.date(year, month, 28)
                
        days_until = (due_date - today).days
        
        if days_until == notify_days:
            messages.append(f"❗️ Напоминание: Оплата '{meta.get('category', fname)}' через {days_until} дн. (Сумма: {meta.get('budget', '?')} ₽)")
            
    if messages:
        # Send to TG
        client = TelegramClient('crm_session', API_ID, API_HASH)
        await client.start()
        
        for msg in messages:
            print(f"Sending reminder: {msg}")
            await client.send_message('me', msg)
            
        await client.disconnect()
    else:
        print("No reminders to send today.")

if __name__ == "__main__":
    asyncio.run(check_reminders())
