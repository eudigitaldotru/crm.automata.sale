import time
import os
import subprocess
import sys
import threading

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Пауза между проверками почты (сек)
EMAIL_CHECK_INTERVAL = 300
# Пауза между лёгкими проверками целостности сайтов (сек)
INTEGRITY_LIGHT_INTERVAL = 3600
# Пауза между проверками репутации доменов (Safe Browsing/VirusTotal, сек)
INTEGRITY_REPUTATION_INTERVAL = 12 * 60 * 60


def run_tg_gateway_client():
    """
    Запускает tg_gateway_client.py в вечном цикле в отдельном потоке.
    Клиент опрашивает зарубежный VPS gateway и складывает входящие
    Telegram-сообщения в 20_Inbox/ и 15_Leads/ (замена сломанному tg_listener.py).
    При падении клиента — перезапуск через 10 сек.
    """
    script = os.path.join(BASE_DIR, "tg_gateway_client.py")
    while True:
        try:
            print("📨 TG-Gateway client: запуск...")
            # Не check=True — клиент сам управляет своим циклом; падение не должно
            # валить весь демон. runs forever, пока не упадёт.
            # Вывод — в файл (терминал никто не читает; инцидент 10.09 с потерей события)
            log_path = os.path.join(os.path.dirname(BASE_DIR), "logs", "poller.log")
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            with open(log_path, "ab") as lf:
                proc = subprocess.run([sys.executable, "-u", script],
                                      cwd=BASE_DIR, check=False, stdout=lf, stderr=lf)
            print(f"⚠️ TG-Gateway client завершился (rc={proc.returncode}), перезапуск через 10с...")
        except Exception as e:
            print(f"❌ TG-Gateway client error: {e}, перезапуск через 10с...")
        time.sleep(10)


def run_max_listener():
    """MAX Bot API long polling: группы клиентов → 20_Inbox/max_*.md."""
    script = os.path.join(BASE_DIR, "max_listener.py")
    while True:
        try:
            print("🟣 MAX listener: запуск...")
            log_path = os.path.join(os.path.dirname(BASE_DIR), "logs", "max_listener.log")
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            with open(log_path, "ab") as lf:
                proc = subprocess.run([sys.executable, "-u", script],
                                      cwd=BASE_DIR, check=False, stdout=lf, stderr=lf)
            print(f"⚠️ MAX listener завершился (rc={proc.returncode}), перезапуск через 10с...")
        except Exception as e:
            print(f"❌ MAX listener error: {e}, перезапуск через 10с...")
        time.sleep(10)


def run_email_checker():
    """
    Проверка почты (IMAP timeweb) в вечном цикле в отдельном потоке.
    Раньше жила в легаси-startup.sh со старыми путями и не запускалась;
    теперь возвращена в работу: письма клиентов → 20_Inbox/ + событие на хаб.
    """
    script = os.path.join(BASE_DIR, "email_to_obsidian.py")
    while True:
        try:
            proc = subprocess.run([sys.executable, "-u", script],
                                  cwd=BASE_DIR, check=False,
                                  capture_output=True, text=True)
            if proc.returncode != 0:
                print(f"⚠️ email checker rc={proc.returncode}: {(proc.stderr or '')[-300:]}")
        except FileNotFoundError:
            print("❌ email_to_obsidian.py не найден — поток почты остановлен")
            return
        except Exception as e:
            print(f"❌ email checker error: {e}")
        time.sleep(EMAIL_CHECK_INTERVAL)


def run_integrity_checker():
    """
    Проверка паттернов взлома сайтов в отдельном потоке:
    лёгкие проверки (целостность/клоакинг/малварь/Битрикс-пути) — раз в час,
    репутация доменов (Safe Browsing/VirusTotal) — раз в 12 часов.
    """
    last_reputation = 0
    while True:
        now = time.time()
        need_reputation = (now - last_reputation) >= INTEGRITY_REPUTATION_INTERVAL
        try:
            print("🛡️ Running integrity check"
                  + (" + reputation" if need_reputation else "") + "...")
            proc = subprocess.run(
                [sys.executable, "-u", os.path.join(BASE_DIR, "integrity_check.py")]
                + (["--reputation"] if need_reputation else []),
                cwd=BASE_DIR, check=False,
                capture_output=True, text=True)
            if proc.returncode != 0:
                print(f"⚠️ integrity check rc={proc.returncode}: {(proc.stderr or '')[-400:]}")
            # после проверок шлём свежий снапшот (в нём появились integrity-поля)
            push_monitoring_snapshot()
        except Exception as e:
            print(f"❌ integrity checker error: {e}")
        if need_reputation:
            last_reputation = time.time()
        time.sleep(INTEGRITY_LIGHT_INTERVAL)


def push_monitoring_snapshot():
    """Отправляет свежий monitoring.json на хаб automata.sale (/status + приложение)."""
    try:
        sys.path.insert(0, BASE_DIR)
        from monitoring_core import load_monitoring_data
        from hub_push import send_monitoring_snapshot
        send_monitoring_snapshot(load_monitoring_data())
    except Exception as e:
        print(f"[hub] snapshot не отправлен: {e}")


VPS_ALERTS_CMD = "cat /opt/crm-uptime/alerts.jsonl 2>/dev/null"
VPS_CURSOR_FILE = os.path.join(BASE_DIR, ".vps_uptime_cursor.json")


def fetch_vps_alerts():
    """
    Забирает события внешнего VPS-мониторинга (каждые 5 мин, append-only jsonl на VPS)
    и материализует их в CRM: site_down → critical-тикет, site_up → авто-закрытие.
    Пуши владельцу уже ушли с VPS через хаб — здесь только тикеты и события ленты.
    Ноутбук оффлайн → забора нет; события копятся на VPS и догоняются при появлении.
    """
    try:
        sys.path.insert(0, BASE_DIR)
        import json as _json
        from uptime_check import create_critical_ticket, auto_close_incident
        from hub_push import send_event

        cursor = 0
        if os.path.exists(VPS_CURSOR_FILE):
            try:
                with open(VPS_CURSOR_FILE) as f:
                    cursor = int(f.read().strip() or 0)
            except Exception:
                cursor = 0

        vps_host = os.getenv("MONITOR_VPS_HOST")
        if not vps_host:
            return
        r = subprocess.run(["ssh", f"root@{vps_host}", VPS_ALERTS_CMD],
                           capture_output=True, text=True, timeout=30, check=False)
        if r.returncode != 0:
            print(f"[vps-alerts] ssh недоступен ({r.returncode}) — заберём позже")
            return

        new_events = []
        for line in r.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ev = _json.loads(line)
            except Exception:
                continue
            if isinstance(ev.get("id"), int) and ev["id"] > cursor:
                new_events.append(ev)

        for ev in new_events:
            etype, domain = ev.get("type"), ev.get("domain", "")
            client = ev.get("client", "")
            if etype == "site_down":
                print(f"[vps-alerts] 🚨 site_down: {domain} ({client})")
                create_critical_ticket(domain, client)
                send_event("site_down", f"Сайт недоступен (VPS-мониторинг): {domain} ({client})",
                           severity="critical", payload={"domain": domain, "client": client, "source": "vps"})
            elif etype == "site_up":
                print(f"[vps-alerts] ✅ site_up: {domain}")
                auto_close_incident(domain)
                send_event("site_up", f"Сайт восстановлен (VPS-мониторинг): {domain} ({client})",
                           severity="info", payload={"domain": domain, "client": client, "source": "vps"})
            if ev["id"] > cursor:
                cursor = ev["id"]

        if new_events:
            with open(VPS_CURSOR_FILE, "w") as f:
                f.write(str(cursor))
            print(f"[vps-alerts] обработано событий: {len(new_events)}, курсор → {cursor}")
    except Exception as e:
        print(f"[vps-alerts] ошибка (не критично): {e}")


def run_integration_alerts():
    """
    Активный алертинг интеграций (TG-контур, MAX, почта) — отдельным потоком
    с коротким циклом: проверки дешёвые и критичные, не должны ждать
    медленный uptime-цикл (при деградации сети тот идёт 5-10 минут).
    Инцидент 28.09: счёт клиенту висел недоставленным, а дашборд молча
    красил светофоры — теперь падения шумят (пуш хаба + тикет + notify-send).
    """
    sys.path.insert(0, BASE_DIR)
    from integration_alerts import check_and_alert
    while True:
        try:
            check_and_alert()
        except Exception as e:
            print(f"[integration_alerts] ошибка (не критично): {e}")
        time.sleep(180)


def run_checks(run_heavy=False):
    try:
        # ПРИМЕЧАНИЕ: sync_from_server.py отключён — endpoint automata.sale/api/sync
        # не работает (HTTP 502) с ~25.06.2026, синхронизация признана устаревшей.

        # Run uptime (every 5 min)
        print("⚡ Running uptime check...")
        subprocess.run([sys.executable, os.path.join(BASE_DIR, "uptime_check.py")], check=True)

        # Забор событий внешнего VPS-мониторинга → тикеты CRM
        fetch_vps_alerts()

        if run_heavy:
            print("🔐 Running heavy checks (SSL, WHOIS, Security, PageSpeed)...")
            subprocess.run([sys.executable, os.path.join(BASE_DIR, "ssl_check.py")], check=False)
            subprocess.run([sys.executable, os.path.join(BASE_DIR, "whois_check.py")], check=False)
            subprocess.run([sys.executable, os.path.join(BASE_DIR, "security_check.py")], check=False)
            subprocess.run([sys.executable, os.path.join(BASE_DIR, "pagespeed_check.py")], check=False)
            print("💳 Running finance reminders check...")
            subprocess.run([sys.executable, os.path.join(BASE_DIR, "finance_reminders.py")], check=False)
            print("✅ Heavy checks complete.")

        # Снапшот на хаб после каждого цикла проверок
        push_monitoring_snapshot()
    except Exception as e:
        print(f"Error in monitoring daemon: {e}")

if __name__ == "__main__":
    print("Monitoring Daemon started...")

    # Запускаем TG-Gateway client в отдельном потоке (вечный long-poll к VPS gateway)
    tg_thread = threading.Thread(target=run_tg_gateway_client, daemon=True)
    max_thread = threading.Thread(target=run_max_listener, daemon=True)
    max_thread.start()
    tg_thread.start()
    print("📨 TG-Gateway client thread started")

    # Проверка почты — тоже отдельный поток (клиентские письма → inbox + пуш)
    email_thread = threading.Thread(target=run_email_checker, daemon=True)
    email_thread.start()
    print("📧 Email checker thread started")

    # Проверка паттернов взлома — отдельный поток (лёгкие раз в час, репутация раз в 12 ч)
    integrity_thread = threading.Thread(target=run_integrity_checker, daemon=True)
    integrity_thread.start()
    print("🛡️ Integrity checker thread started")

    # Алертинг интеграций — отдельный поток, цикл 3 мин
    alerts_thread = threading.Thread(target=run_integration_alerts, daemon=True)
    alerts_thread.start()
    print("🚨 Integration alerts thread started")

    last_heavy_run = 0
    HEAVY_CHECK_INTERVAL = 12 * 60 * 60  # 12 hours

    while True:
        now = time.time()
        should_run_heavy = (now - last_heavy_run) >= HEAVY_CHECK_INTERVAL

        run_checks(run_heavy=should_run_heavy)

        if should_run_heavy:
            last_heavy_run = now

        # Sleep 5 minutes
        time.sleep(300)

