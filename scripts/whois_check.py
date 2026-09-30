import socket
import re
import datetime
import os
import asyncio
from dotenv import load_dotenv
from telethon import TelegramClient
from monitoring_core import sync_domains_with_monitoring, save_monitoring_data, BASE_PATH

def query_whois(domain, whois_server):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(5.0)
    try:
        s.connect((whois_server, 43))
        s.send((domain + "\r\n").encode("utf-8"))
        response = b""
        while True:
            data = s.recv(4096)
            if not data:
                break
            response += data
        return response.decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"Error querying {whois_server} for {domain}: {e}")
        return None
    finally:
        s.close()

def get_whois_data(domain):
    try:
        domain_idna = domain.encode('idna').decode('ascii')
    except Exception as e:
        print(f"IDNA encode error for {domain}: {e}")
        domain_idna = domain

    tld = domain_idna.split('.')[-1].lower()
    
    if tld in ['ru', 'su', 'rf']:
        server = 'whois.tcinet.ru'
    elif tld in ['com', 'net']:
        server = 'whois.verisign-grs.com'
    elif tld in ['org']:
        server = 'whois.pir.org'
    else:
        server = 'whois.iana.org'
        
    res = query_whois(domain_idna, server)
    if res and server == 'whois.iana.org':
        for line in res.splitlines():
            if line.strip().startswith('refer:'):
                ref_server = line.split(':', 1)[1].strip()
                res_ref = query_whois(domain_idna, ref_server)
                if res_ref:
                    return res_ref
    return res

def parse_expiry_date(whois_text):
    if not whois_text:
        return None
    
    patterns = [
        r'(?:paid-till|Registry Expiry Date|Expiration Date|expiry|expires|Expiration Time|Expires On)\s*:\s*([\d\w\-.:\s]+)',
        r'(?:Expiration date|Expiration Date)\.+\:\s*([\d\w\-.:\s]+)'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, whois_text, re.IGNORECASE)
        if match:
            date_str = match.group(1).strip()
            date_clean = re.split(r'[T\s]', date_str)[0]
            
            # YYYY-MM-DD
            match_ymd = re.search(r'(\d{4})[-./](\d{2})[-./](\d{2})', date_clean)
            if match_ymd:
                return datetime.datetime(int(match_ymd.group(1)), int(match_ymd.group(2)), int(match_ymd.group(3)))
            
            # DD-MM-YYYY
            match_dmy = re.search(r'(\d{2})[-./](\d{2})[-./](\d{4})', date_clean)
            if match_dmy:
                return datetime.datetime(int(match_dmy.group(3)), int(match_dmy.group(2)), int(match_dmy.group(1)))
                
            for fmt in ('%Y-%m-%d', '%d.%m.%Y', '%d-%b-%Y', '%d-%B-%Y'):
                try:
                    return datetime.datetime.strptime(date_clean, fmt)
                except ValueError:
                    continue
    return None

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
        print("Alert sent via Telegram.")
    except Exception as e:
        print(f"Failed to send Telegram alert: {e}")
    finally:
        await client.disconnect()

def check_domain_expiration():
    data = sync_domains_with_monitoring()
    alerts = []
    
    for item in data:
        domain = item['domain']
        print(f"Checking WHOIS for {domain}...")
        
        raw_whois = get_whois_data(domain)
        expiry_date = parse_expiry_date(raw_whois)
        
        if expiry_date:
            expiry_str = expiry_date.strftime('%Y-%m-%d')
            item['domainExpiryDate'] = expiry_str
            item['lastChecked'] = datetime.datetime.utcnow().isoformat() + "Z"
            
            days_left = (expiry_date - datetime.datetime.utcnow()).days
            if days_left < 30:
                alerts.append(f"⚠️ Внимание! Домен {domain} истекает через {days_left} дней ({expiry_str})!")
        else:
            item['domainExpiryDate'] = "Error"
            item['lastChecked'] = datetime.datetime.utcnow().isoformat() + "Z"
            alerts.append(f"❌ Ошибка проверки продления домена для {domain}!")

    save_monitoring_data(data)
    print("WHOIS check complete.")
    
    if alerts:
        combined_alert = "🌐 **Сводка по продлению доменов (WHOIS)**\n\n" + "\n".join(alerts)
        asyncio.run(send_telegram_alert(combined_alert))

if __name__ == "__main__":
    check_domain_expiration()
