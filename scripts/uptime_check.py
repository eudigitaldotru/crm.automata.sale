
from sec_guard import guard_open, guard_requests_get
import os
import time
import uuid
import datetime
import requests
from monitoring_core import sync_domains_with_monitoring, save_monitoring_data, BASE_PATH
from hub_push import send_event

TICKETS_DIR = os.path.join(BASE_PATH, "45_Tickets")

# Сколько попыток проверки перед объявлением сайта упавшим.
# При холодном старте ПК (сеть/DNS ещё не установились) первая проверка может
# упасть — повторные попытки отсекают ложные тревоги.
MAX_RETRIES = 3
RETRY_DELAY = 5  # сек между попытками

# Порог «сайт доступен, но тормозит» (мс). Сайт был UP, но с мёртвым кешем
# работал в 4 раза медленнее — по статусу это не видно, по времени ответа видно.
# Алерт при переходе через SLOW_MS, снятие — когда время вернулось ниже RECOVER_MS.
SLOW_MS = 2000
RECOVER_MS = 1000

# ── Эталонные хосты канала ──
# Если недоступны ВСЕ — интернета нет у ноутбука, а не у сайтов: проверку
# пропускаем, статусы не портим, тикетов не создаём (кейс 27.09: 13 ложных
# critical-тикетов при сбое локального канала).
REFERENCE_HOSTS = ["https://ya.ru", "https://1.1.1.1"]


def network_alive():
    """True, если доступен хотя бы один эталонный хост (канал жив)."""
    for url in REFERENCE_HOSTS:
        try:
            ok, _ = check_once(url, timeout=6)
            if ok:
                return True
        except Exception:
            continue
    return False


def check_once(url, timeout=10):
    """Одна попытка HTTP-запроса. Возвращает (True если сайт отвечает < 400, время ответа в мс)."""
    try:
        resp = guard_requests_get(url, timeout=timeout)
        elapsed_ms = int(resp.elapsed.total_seconds() * 1000)
        return resp.status_code < 400, elapsed_ms
    except Exception as e:
        print(f"   попытка провалилась: {e}")
        return False, None


def check_with_retries(url, domain):
    """
    Проверяет сайт несколько раз с паузой. Только если ВСЕ попытки провалились —
    сайт считается упавшим. Это защищает от ложных тревог при холодном старте
    (когда сеть/DNS ещё не установились после включения ПК).
    Возвращает (is_up, время ответа успешной попытки в мс или None).
    """
    for attempt in range(1, MAX_RETRIES + 1):
        is_up, elapsed_ms = check_once(url)
        if is_up:
            return True, elapsed_ms
        if attempt < MAX_RETRIES:
            print(f"   ⚠️ {domain}: попытка {attempt}/{MAX_RETRIES} провалена, повтор через {RETRY_DELAY}с...")
            time.sleep(RETRY_DELAY)
    return False, None


def check_uptime():
    # Гейт канала: нет эталонных хостов → интернет пропал у ноутбука.
    if not network_alive():
        print("👁 Мониторинг ослеп: эталонные хосты недоступны — пропускаю проверку "
              "(статусы не меняю, тикетов не создаю).")
        send_event(
            "monitor_blind",
            "Мониторинг ослеп: локальный канал недоступен, проверка сайтов пропущена",
            dedup_key=f"blind-{datetime.date.today().isoformat()}",
            severity="warning",
            payload={"reference_hosts": REFERENCE_HOSTS},
        )
        return

    data = sync_domains_with_monitoring()

    for item in data:
        url = item['url']
        domain = item['domain']
        client_name = item['name']
        print(f"Checking uptime for {domain}...")

        is_up, elapsed_ms = check_with_retries(url, domain)

        old_status = item.get('status', 'unknown')
        new_status = "up" if is_up else "down"

        item['status'] = new_status
        item['lastChecked'] = datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00', 'Z')
        if elapsed_ms is not None:
            item['responseTimeMs'] = elapsed_ms

        # ── Алерт «сайт тормозит»: доступен, но медленнее порога ──
        old_slow = bool(item.get('slow', False))
        is_slow = is_up and elapsed_ms is not None and elapsed_ms >= SLOW_MS
        recovered_speed = (not is_up) or (elapsed_ms is not None and elapsed_ms <= RECOVER_MS)
        if is_slow and not old_slow:
            item['slow'] = True
            print(f"🐌 SITE SLOW: {domain} — {elapsed_ms} мс (порог {SLOW_MS} мс)")
            send_event(
                "site_slow",
                f"Сайт тормозит: {domain} ({client_name}) — {elapsed_ms} мс",
                dedup_key=f"slow-{domain}-{datetime.date.today().isoformat()}",
                severity="warning",
                payload={"domain": domain, "client": client_name, "responseTimeMs": elapsed_ms},
                push={"title": f"🐌 {domain} отвечает медленно", "body": f"{elapsed_ms} мс (порог {SLOW_MS} мс)", "channel": "default"},
            )
        elif old_slow and recovered_speed:
            item['slow'] = False
            print(f"⚡ SPEED RECOVERED: {domain}")
            send_event(
                "site_speed_ok",
                f"Скорость восстановлена: {domain} ({client_name})",
                dedup_key=f"slow-ok-{domain}-{datetime.date.today().isoformat()}",
                severity="info",
                payload={"domain": domain, "client": client_name},
            )

        # ── Инциденты up/down: решает VPS-мониторинг (автономен от канала ноутбука).
        # Ноутбук только фиксирует статусы (для Analytics/ленты); тикеты и крит-пуши
        # создаются ноутом из событий VPS (см. monitoring_daemon → fetch_vps_alerts).
        if new_status == "down" and old_status != "down":
            print(f"🚨 SITE DOWN (локальная фиксация, тикет — от VPS-мониторинга): {domain}")
        elif new_status == "up" and old_status == "down":
            print(f"✅ SITE RECOVERED (локальная фиксация): {domain}")

    save_monitoring_data(data)
    print("Uptime check complete.")

def create_critical_ticket(domain, client_name):
    os.makedirs(TICKETS_DIR, exist_ok=True)
    
    # Check if there is already an open incident for this domain
    for fname in os.listdir(TICKETS_DIR):
        if not fname.endswith(".md"): continue
        with guard_open(os.path.join(TICKETS_DIR, fname), 'r', encoding='utf-8') as f:
            content = f.read()
            if domain in content and "status: open" in content and "priority: critical" in content:
                print(f"Ticket for {domain} already exists, skipping.")
                return
                
    ticket_id = f"ticket-{str(uuid.uuid4())[:6]}"
    now = datetime.datetime.now()
    deadline = now + datetime.timedelta(hours=1) # 1 hour SLA for critical incidents
    
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M:%S")
    
    frontmatter = f"""---
id: {ticket_id}
created: {date_str} {time_str}
client: "[[{client_name}]]"
title: "КРИТИЧНО: Упал сайт {domain}"
status: open
priority: critical
tags:
  - ticket
  - incident
sla_hours: 1
sla_deadline: {deadline.strftime('%Y-%m-%d %H:%M:%S')}
alert_sent: false
---

# Инцидент: Недоступность сайта {domain}

Сайт `{domain}` перестал отвечать на запросы (ошибка HTTP или таймаут).
Обнаружено автоматическим мониторингом: **{date_str} {time_str}**.

Срочно проверьте:
1. Оплачен ли хостинг/домен.
2. Работает ли веб-сервер (Nginx/Apache).
3. Доступность базы данных.

[[{client_name}]]
"""
    file_path = os.path.join(TICKETS_DIR, f"{ticket_id}.md")
    with guard_open(file_path, "w", encoding="utf-8") as f:
        f.write(frontmatter)
    print(f"🎫 Created critical ticket: {ticket_id} for {domain}")


def auto_close_incident(domain):
    """
    Авто-закрывает открытый critical-инцидент для домена при восстановлении сайта.
    Меняет status: open → closed и добавляет пометку о восстановлении.
    """
    if not os.path.exists(TICKETS_DIR):
        return
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    for fname in os.listdir(TICKETS_DIR):
        if not fname.endswith(".md"):
            continue
        fpath = os.path.join(TICKETS_DIR, fname)
        try:
            with guard_open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
            if domain in content and "status: open" in content and "priority: critical" in content:
                new = content.replace("status: open", "status: closed", 1)
                note = f"\n\n---\n✅ **Сайт восстановлен** ({now_str}). Инцидент закрыт автоматически мониторингом.\n"
                if "закрыт автоматически" not in new:
                    new = new.rstrip() + note
                with guard_open(fpath, "w", encoding="utf-8") as f:
                    f.write(new)
                print(f"🔧 Auto-closed incident for {domain}: {fname}")
        except Exception as e:
            print(f"⚠️ auto_close_incident {fname}: {e}")


if __name__ == "__main__":
    check_uptime()
