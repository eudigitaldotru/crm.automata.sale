import ssl
import socket
import datetime
import os
from dotenv import load_dotenv
from monitoring_core import sync_domains_with_monitoring, save_monitoring_data, BASE_PATH

def get_ssl_expiry_date(hostname):
    context = ssl.create_default_context()
    conn = context.wrap_socket(socket.socket(socket.AF_INET), server_hostname=hostname)
    # 3 second timeout for socket
    conn.settimeout(3.0)

    try:
        conn.connect((hostname, 443))
        ssl_info = conn.getpeercert()
        # ssl_info['notAfter'] is like 'Aug 14 12:00:00 2026 GMT'
        expiry_str = ssl_info.get('notAfter')
        if not expiry_str:
            return None
        
        # Parse the date
        expiry_date = datetime.datetime.strptime(expiry_str, '%b %d %H:%M:%S %Y %Z')
        return expiry_date
    except Exception as e:
        print(f"Error checking SSL for {hostname}: {e}")
        return None
    finally:
        conn.close()

def send_telegram_alert(message):
    """Алерты владельцу через tg-gateway: userbot (аккаунт владельца) шлёт
    сообщение самому себе — они приходят в Saved Messages."""
    load_dotenv(os.path.join(BASE_PATH, ".env"))
    admin = os.getenv("ADMIN_TG_ID") or os.getenv("MY_USER_ID")
    if not admin:
        print("Нет TG-адресата в .env (ADMIN_TG_ID/MY_USER_ID) — алерт не отправлен.")
        return

    from tg_outbound import send_via_gateway
    result = send_via_gateway(admin, message)
    if result.get("ok"):
        print("Alert sent via Telegram (gateway → Saved Messages).")
    else:
        print(f"Failed to send Telegram alert: {result.get('error')}")

def check_ssl_certificates():
    data = sync_domains_with_monitoring()
    alerts = []
    
    for item in data:
        domain = item['domain']
        print(f"Checking SSL for {domain}...")
        
        expiry_date = get_ssl_expiry_date(domain)
        
        if expiry_date:
            # format as YYYY-MM-DD
            item['expiryDate'] = expiry_date.strftime('%Y-%m-%d')
            item['lastChecked'] = datetime.datetime.utcnow().isoformat() + "Z"
            
            days_left = (expiry_date - datetime.datetime.utcnow()).days
            if days_left < 30:
                alerts.append(f"⚠️ Внимание! SSL сертификат для {domain} истекает через {days_left} дней ({item['expiryDate']})!")
        else:
            item['expiryDate'] = "Error"
            item['lastChecked'] = datetime.datetime.utcnow().isoformat() + "Z"
            alerts.append(f"❌ Ошибка проверки SSL для {domain}!")

    save_monitoring_data(data)
    print("SSL check complete.")
    
    if alerts:
        combined_alert = "🔐 **Сводка по SSL сертификатам**\n\n" + "\n".join(alerts)
        send_telegram_alert(combined_alert)

if __name__ == "__main__":
    check_ssl_certificates()
