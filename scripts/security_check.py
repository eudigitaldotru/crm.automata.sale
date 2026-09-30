
from sec_guard import guard_open, guard_requests_get
import os
import requests
import datetime
import uuid
import re
import asyncio
from dotenv import load_dotenv
from telethon import TelegramClient
from monitoring_core import sync_domains_with_monitoring, save_monitoring_data, BASE_PATH

TICKETS_DIR = os.path.join(BASE_PATH, "45_Tickets")

def is_valid_env(content):
    # Search for typical env keys assigned to variables to avoid false positives (e.g. custom html error pages)
    keywords = ["DB_PASSWORD", "DB_HOST", "APP_KEY", "API_KEY", "DB_CONNECTION", "JWT_SECRET", "AWS_ACCESS_KEY_ID", "MYSQL_ROOT_PASSWORD", "DATABASE_URL"]
    for key in keywords:
        if re.search(r'^\s*' + key + r'\s*=', content, re.IGNORECASE | re.MULTILINE):
            return True
    return False

def is_valid_git_config(content):
    # Search for typical git config sections to avoid false positives
    keywords = ["repositoryformatversion", "[core]", '[remote "origin"]']
    for key in keywords:
        if key in content:
            return True
    return False

async def send_telegram_alert(message):
    load_dotenv(os.path.join(BASE_PATH, ".env"))
    API_ID = os.getenv("API_ID")
    API_HASH = os.getenv("API_HASH")
    ADMIN_TG_ID = os.getenv("ADMIN_TG_ID")
    
    if not all([API_ID, API_HASH, ADMIN_TG_ID]):
        print("Missing Telegram credentials. Cannot send alert.")
        return

    session_file = os.path.join(BASE_PATH, 'scripts', 'invoice_session')
    client = TelegramClient(session_file, int(API_ID), API_HASH)
    
    try:
        await client.connect()
        if not await client.is_user_authorized():
            print("Client is not authorized. Start tg_listener to auth.")
            return
            
        await client.send_message(int(ADMIN_TG_ID), message)
        print("Security Alert sent via Telegram.")
    except Exception as e:
        print(f"Failed to send Telegram alert: {e}")
    finally:
        await client.disconnect()

def create_security_ticket(domain, client_name, exposed_files):
    os.makedirs(TICKETS_DIR, exist_ok=True)
    
    # Check if there is already an open security ticket for this domain
    for fname in os.listdir(TICKETS_DIR):
        if not fname.endswith(".md"): continue
        try:
            with guard_open(os.path.join(TICKETS_DIR, fname), 'r', encoding='utf-8') as f:
                content = f.read()
                if domain in content and "status: open" in content and "priority: critical" in content and "security" in content:
                    print(f"Security ticket for {domain} already exists, skipping.")
                    return
        except:
            pass
                 
    ticket_id = f"ticket-sec-{str(uuid.uuid4())[:6]}"
    now = datetime.datetime.now()
    deadline = now + datetime.timedelta(hours=1) # 1 hour SLA for critical security incidents
    
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M:%S")
    
    files_list = "\n".join([f"- `{f}`" for f in exposed_files])
    
    frontmatter = f"""---
id: {ticket_id}
created: {date_str} {time_str}
client: "[[{client_name}]]"
title: "КРИТИЧНО: Утечка данных на {domain}"
status: open
priority: critical
tags:
  - ticket
  - incident
  - security
sla_hours: 1
sla_deadline: {deadline.strftime('%Y-%m-%d %H:%M:%S')}
alert_sent: false
---

# Инцидент безопасности: Открытые файлы конфигурации на {domain}

На сайте `{domain}` обнаружены публично доступные критические файлы конфигурации:
{files_list}

**Срочно примите меры:**
1. Закройте публичный доступ к данным путям в конфигурации веб-сервера (Nginx/Apache/.htaccess).
2. Смените ВСЕ пароли баз данных, API-ключи и секреты приложения, которые были указаны в скомпрометированных файлах!

[[{client_name}]]
"""
    file_path = os.path.join(TICKETS_DIR, f"{ticket_id}.md")
    with guard_open(file_path, "w", encoding="utf-8") as f:
        f.write(frontmatter)
    print(f"🎫 Created critical security ticket: {ticket_id} for {domain}")

def check_security():
    data = sync_domains_with_monitoring()
    alerts = []
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) MonitoringScanner/1.0'
    }
    
    for item in data:
        url = item['url']
        domain = item['domain']
        client_name = item['name']
        
        # Skip if site is down
        if item.get("status") == "down":
            print(f"Skipping security scan for {domain} (Site is down)")
            continue
            
        print(f"Scanning security for {domain}...")
        exposed = []
        
        # Test .env
        try:
            _u = f"{url.rstrip('/')}/.env"
            resp = guard_requests_get(_u, headers=headers, timeout=5, allow_redirects=False)
            if resp.status_code == 200 and is_valid_env(resp.text):
                print(f"🚨 Exposed .env found on {domain}!")
                exposed.append(".env")
        except Exception as e:
            print(f"Error checking .env for {domain}: {e}")
            
        # Test .git/config
        try:
            _u = f"{url.rstrip('/')}/.git/config"
            resp = guard_requests_get(_u, headers=headers, timeout=5, allow_redirects=False)
            if resp.status_code == 200 and is_valid_git_config(resp.text):
                print(f"🚨 Exposed .git/config found on {domain}!")
                exposed.append(".git/config")
        except Exception as e:
            print(f"Error checking .git/config for {domain}: {e}")
            
        old_exposed = item.get('exposedFiles', [])
        item['exposedFiles'] = exposed
        item['lastChecked'] = datetime.datetime.utcnow().isoformat() + "Z"
        
        if exposed:
            # Check if there are newly found exposed files compared to old run
            new_leaks = set(exposed) - set(old_exposed)
            if new_leaks:
                alerts.append(f"🚨 **КРИТИЧЕСКАЯ УЯЗВИМОСТЬ** на {domain} ({client_name})! Открыт доступ к: {', '.join(new_leaks)}")
                create_security_ticket(domain, client_name, exposed)

    save_monitoring_data(data)
    print("Security check complete.")
    
    if alerts:
        combined_alert = "🔥 **Алерт безопасности сайтов**\n\n" + "\n".join(alerts)
        asyncio.run(send_telegram_alert(combined_alert))

if __name__ == "__main__":
    check_security()
