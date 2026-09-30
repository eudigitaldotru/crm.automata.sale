#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Активный алертинг интеграций CRM.

Инцидент 28.09: TG-шлюз на VPS умер, сообщения клиенту (счёт!) висели
недоставленными часами, а вкладка «Система» дашборда только красила
светофоры — владелец узнал случайно. Этот модень делает падения
шумными: проверяет интеграции и на ПЕРЕХОДЕ ok→down (и обратно)
рассылает алерты через каналы, НЕ зависящие от проверяемого контура:

  1. push через хаб automata.sale (hub_push.send_event, push=...)
  2. critical-тикет в 45_Tickets (ticket-ops-<key>-auto.md, авто-закрытие)
  3. notify-send на ноутбуке владельца

Запускается из monitoring_daemon.py каждые 5 минут (run_checks).
Состояние — scripts/.integration_alerts_state.json; алерт не спамит:
один на переход + напоминание раз в 2 часа, пока сбой держится.

Ограничение (TODO): зависшие в status=sending отправки шлюз не показывает
в /health — нужен эндпоинт /internal/outbox/stuck в gateway.py на VPS
(код в AUTOMATA-CRM/tg-gateway), после его деплоя добавить сюда проверку.
"""
import imaplib
import json
import os
import socket
import ssl as _ssl
import subprocess
import sys
import time
import urllib.request as _ur
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent          # AUTOMATA-CRM
SCRIPTS = BASE_DIR / "scripts"
STATE_FILE = SCRIPTS / ".integration_alerts_state.json"
TICKETS_DIR = BASE_DIR / "45_Tickets"
LOG_FILE = BASE_DIR / "logs" / "integration_alerts.log"

RE_ALERT_INTERVAL = 2 * 60 * 60       # напоминание о живом сбое — раз в 2ч
QUEUE_GRACE_SEC = 15 * 60             # очередь>0 меньше 15 мин — не алерт


def _env():
    data = {}
    for line in (BASE_DIR / ".env").read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            data[k] = v.strip().strip('"').strip("'")
    return data


def _log(msg):
    line = f"[{time.strftime('%d.%m %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        LOG_FILE.parent.mkdir(exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Проверки: каждая возвращает (ok: bool, detail: str)
# ---------------------------------------------------------------------------

_VPS_HOST = os.getenv("TG_GATEWAY_VPS_HOST", "")
_VPS_PORT = os.getenv("TG_GATEWAY_VPS_PORT", "22")
SSH_VPS_CMD = (["ssh", "-p", _VPS_PORT, "-o", "ConnectTimeout=8", "-o",
                "BatchMode=yes", f"root@{_VPS_HOST}",
                "curl -s --max-time 6 http://127.0.0.1:8443/health"] if _VPS_HOST else None)
RESTART_HINT = "лечение: systemctl restart tg-userbot на VPS шлюза"


def _tg_health_ssh():
    """Health шлюза ИЗНУТРИ VPS по SSH (порт 3333) — канал переживает транзитные
    волны, когда прямая сеть к VPS лежит (инцидент 28-29.09: HTTP таймаутил,
    SSH работал). Возвращает dict health или None."""
    if not SSH_VPS_CMD:
        return None
    try:
        r = subprocess.run(SSH_VPS_CMD, capture_output=True, text=True, timeout=15)
        if r.returncode != 0 or not r.stdout.strip():
            return None
        return json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        return None


def check_tg_ssh_channel(env):
    """SSH-канал до VPS-шлюза (порт 3333) — путь диагностики и лечения."""
    try:
        r = subprocess.run(
            ["ssh", "-p", _VPS_PORT, "-o", "ConnectTimeout=8", "-o", "BatchMode=yes",
             f"root@{_VPS_HOST}", "echo ok"], capture_output=True, text=True, timeout=15)
        if r.returncode == 0 and r.stdout.strip():
            return True, "SSH :3333 доступен (канал диагностики жив)"
        return False, "SSH :3333 недоступен — лечение только вручную"
    except Exception as e:
        return False, f"SSH :3333: {str(e)[:60]}"


def check_tg_gateway(env):
    """Шлюз доступен и отвечает на /health (сама очередь — отдельно).
    При таймауте прямой сети — арбитраж по SSH-каналу (порт 3333), чтобы
    транзитная волна не давала ложный down."""
    try:
        ctx = _ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = _ssl.CERT_NONE
        req = _ur.Request(env.get("TG_GATEWAY_URL", "").rstrip("/") + "/health",
                          headers={"Authorization": f"Bearer {env.get('TG_GATEWAY_TOKEN', '')}"})
        with _ur.urlopen(req, timeout=10, context=ctx) as r:
            d = json.loads(r.read().decode())
        return True, f"ok · events={d.get('events')} · pending={d.get('pending_outbox')}"
    except Exception as e:
        d = _tg_health_ssh()
        if d and d.get("ok"):
            return True, (f"ok по SSH-каналу (прямая сеть лежит: {str(e)[:40]}) · "
                          f"events={d.get('events')} · pending={d.get('pending_outbox')}")
        return False, f"недоступен и по прямой, и по SSH: {str(e)[:60]}"


def check_tg_userbot(env):
    """Userbot шлёт heartbeat (>90с = сбой) — главный симптом смерти воркера."""
    try:
        ctx = _ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = _ssl.CERT_NONE
        req = _ur.Request(env.get("TG_GATEWAY_URL", "").rstrip("/") + "/health",
                          headers={"Authorization": f"Bearer {env.get('TG_GATEWAY_TOKEN', '')}"})
        with _ur.urlopen(req, timeout=10, context=ctx) as r:
            d = json.loads(r.read().decode())
        ub = d.get("userbot") or {}
        if ub.get("alive"):
            return True, f"heartbeat жив · {(ub.get('me') or {}).get('name', '?')}"
        return False, f"heartbeat пропал (>90с) — {RESTART_HINT}"
    except Exception as e:
        d = _tg_health_ssh()
        if d:
            ub = d.get("userbot") or {}
            if ub.get("alive"):
                return True, f"heartbeat жив (по SSH-каналу) · прямая сеть: {str(e)[:30]}"
            return False, f"heartbeat пропал — {RESTART_HINT}"
        return False, f"шлюз не отвечает (прямая и SSH): {str(e)[:60]}"


def check_tg_queue(env):
    """pending outbox: копится дольше QUEUE_GRACE_SEC при живом шлюзе = воркер не забирает."""
    try:
        ctx = _ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = _ssl.CERT_NONE
        req = _ur.Request(env.get("TG_GATEWAY_URL", "").rstrip("/") + "/health",
                          headers={"Authorization": f"Bearer {env.get('TG_GATEWAY_TOKEN', '')}"})
        with _ur.urlopen(req, timeout=10, context=ctx) as r:
            d = json.loads(r.read().decode())
        pending = int(d.get("pending_outbox") or 0)
        if pending <= 0:
            return True, "очередь пуста"
        return False, f"pending outbox = {pending} (доставка стоит) — {RESTART_HINT}"
        # grace-логика для этой проверки — в _evaluate (по времени непрерывности)
    except Exception as e:
        d = _tg_health_ssh()
        if d:
            pending = int(d.get("pending_outbox") or 0)
            if pending <= 0:
                return True, "очередь пуста (по SSH-каналу)"
            return False, f"pending outbox = {pending} (доставка стоит) — {RESTART_HINT}"
        return False, f"шлюз не отвечает (прямая и SSH): {str(e)[:60]}"


def check_tg_poller(env):
    alive = subprocess.run(["pgrep", "-f", "tg_gateway_client.py"],
                           capture_output=True).returncode == 0
    return (True, "процесс жив") if alive else (False, "процесс tg_gateway_client.py не найден")


def check_max_bot(env):
    try:
        req = _ur.Request("https://botapi.max.ru/me",
                          headers={"Authorization": env.get("MAX_BOT_TOKEN", "")})
        with _ur.urlopen(req, timeout=10) as r:
            json.loads(r.read().decode())
        return True, "Bot API отвечает"
    except Exception as e:
        return False, f"Bot API: {str(e)[:80]}"


def check_max_listener(env):
    alive = subprocess.run(["pgrep", "-f", "max_listener.py"],
                           capture_output=True).returncode == 0
    return (True, "процесс жив") if alive else (False, "процесс max_listener.py не найден")


def check_mail_imap(env):
    try:
        m = imaplib.IMAP4_SSL(env.get("EMAIL_IMAP_HOST", "imap.timeweb.ru"), timeout=10)
        m.login(env["EMAIL_USER"], env["EMAIL_PASS"])
        m.select("inbox")
        m.logout()
        return True, "IMAP логин ок"
    except Exception as e:
        return False, f"IMAP: {str(e)[:80]}"


def check_mail_smtp(env):
    try:
        with socket.create_connection(
                (env.get("EMAIL_SMTP_HOST", "smtp.timeweb.ru"),
                 int(env.get("EMAIL_SMTP_PORT", "465"))), timeout=8):
            return True, "SMTP TCP ок"
    except Exception as e:
        return False, f"SMTP: {str(e)[:80]}"


CHECKS = [
    ("tg-gateway",   check_tg_gateway,   "🟢 TG-шлюз (VPS)"),
    ("tg-ssh",       check_tg_ssh_channel, "🔐 SSH-канал VPS :3333"),
    ("tg-userbot",   check_tg_userbot,   "🤖 TG Userbot"),
    ("tg-queue",     check_tg_queue,     "📤 TG-очередь доставки"),
    ("tg-poller",    check_tg_poller,    "📥 TG-поллер (локальный)"),
    ("max-bot",      check_max_bot,      "🟣 MAX Bot API"),
    ("max-listener", check_max_listener, "🟣 MAX listener"),
    ("mail-imap",    check_mail_imap,    "✉️ Почта IMAP"),
    ("mail-smtp",    check_mail_smtp,    "📤 Почта SMTP"),
]


# ---------------------------------------------------------------------------
# Тикеты CRM: ticket-ops-<key>-auto.md, создаются на сбой, закрываются на recovery
# ---------------------------------------------------------------------------

def _ticket_path(key):
    return TICKETS_DIR / f"ticket-ops-{key}-auto.md"


def _open_ticket(key, title, detail):
    _ticket_path(key).write_text(
        f"---\nid: ticket-ops-{key}-auto\ncreated: {time.strftime('%Y-%m-%dT%H:%M:%S')}\n"
        f"client: \"[[Automata]]\"\ntitle: \"АВТО-алерт: {title}\"\nstatus: open\n"
        f"priority: high\ntags:\n  - ticket\n  - ops\n  - auto-alert\n---\n\n"
        f"# АВТО-алерт: {title}\n\n**Детали:** {detail}\n\n"
        f"**Когда:** {time.strftime('%d.%m.%Y %H:%M')}\n\n"
        f"Тикет создан автоматически `scripts/integration_alerts.py` "
        f"(переход ok→down). Закроется автоматически при восстановлении.\n",
        encoding="utf-8")


def _close_ticket(key, detail):
    p = _ticket_path(key)
    if not p.exists():
        return
    txt = p.read_text(encoding="utf-8")
    txt = txt.replace("status: open", "status: done")
    txt += (f"\n## ✅ Восстановлено {time.strftime('%d.%m.%Y %H:%M')}\n\n{detail}\n"
            f"Тикет закрыт автоматически.\n")
    p.write_text(txt, encoding="utf-8")


# ---------------------------------------------------------------------------
# Алерт-каналы (независимы от проверяемого контура)
# ---------------------------------------------------------------------------

def _notify_send(title, body):
    """Desktop-уведомление на ноутбуке владельца (WAYLAND/X11)."""
    try:
        env = dict(os.environ)
        if not env.get("DISPLAY") and not env.get("WAYLAND_DISPLAY"):
            return
        subprocess.run(["notify-send", "-u", "critical", "-t", 0,
                        f"CRM: {title}", body[:200]],
                       timeout=5, check=False, env=env)
    except Exception:
        pass


def _hub_alert(kind, key, title, body, severity="critical"):
    try:
        sys.path.insert(0, str(SCRIPTS))
        from hub_push import send_event
        send_event(
            kind, title,
            dedup_key=f"ialert-{key}-{int(time.time())}",
            severity=severity,
            payload={"check": key, "source": "integration_alerts"},
            push={"title": title[:64], "body": body[:160], "channel": "default"},
        )
    except Exception as e:
        _log(f"[hub] алерт не ушёл ({e})")


# ---------------------------------------------------------------------------
# Главная: снять состояние, сравнить, разослать алерты по переходам
# ---------------------------------------------------------------------------

def _load_state():
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def _save_state(st):
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1))
    tmp.replace(STATE_FILE)


def check_and_alert():
    env = _env()
    st = _load_state()
    now = time.time()
    changed = False

    for key, fn, label in CHECKS:
        try:
            ok, detail = fn(env)
        except Exception as e:
            ok, detail = False, f"ошибка проверки: {e}"

        prev = st.get(key) or {}
        prev_alerted = bool(prev.get("alerted"))
        was_down = bool(prev.get("is_down"))

        raw_down = not ok
        down_since = prev.get("down_since") or now
        # tg-queue: непустая очередь — алерт не сразу, а если непрерывно
        # дольше QUEUE_GRACE_SEC (воркер реально не забирает)
        is_down = raw_down
        if key == "tg-queue" and raw_down:
            is_down = (now - down_since) >= QUEUE_GRACE_SEC

        def _save(ok_v, is_down_v, since, alerted, last_notify):
            st[key] = {"ok": ok_v, "is_down": is_down_v, "down_since": since,
                       "alerted": alerted, "last_notify": last_notify, "detail": detail}
            return True

        if is_down and not prev_alerted:
            # переход ok→down или холодный старт сразу в сбое — шумим
            changed = _save(False, True, down_since, True, now)
            title = f"{label} — сбой"
            _log(f"🚨 DOWN {key}: {detail}")
            _notify_send(title, detail)
            _hub_alert("integration_down", key, title, detail, "critical")
            try:
                _open_ticket(key, label, detail)
            except Exception as e:
                _log(f"[ticket] не создан: {e}")
        elif is_down and prev_alerted:
            # сбой держится: напоминание не чаще RE_ALERT_INTERVAL
            if now - prev.get("last_notify", 0) >= RE_ALERT_INTERVAL:
                changed = _save(False, True, down_since, True, now)
                _log(f"⏳ STILL DOWN {key}: {detail}")
                _hub_alert("integration_down", key, f"{label} — сбой продолжается",
                           detail, "critical")
                _notify_send(f"{label} — всё ещё сбой", detail)
        elif not raw_down and was_down:
            # down→ok: recovery
            mins = int((now - down_since) / 60)
            changed = _save(True, False, 0, False, 0)
            _log(f"✅ UP {key}: {detail}")
            _notify_send(f"{label} — восстановлено", f"Простой ~{mins} мин. {detail}")
            _hub_alert("integration_up", key, f"{label} — восстановлено",
                       f"Простой ~{mins} мин. {detail}", "info")
            try:
                _close_ticket(key, detail)
            except Exception as e:
                _log(f"[ticket] не закрыт: {e}")
        elif raw_down and not is_down:
            # grace-период очереди: копим down_since, молчим
            changed = _save(False, False, down_since, False, 0)
            _log(f"… grace {key}: {detail}")
        else:
            # стабильно ок (или холодный старт в ок) — просто обновляем detail
            if not prev or prev.get("detail") != detail:
                changed = _save(True, False, 0, False, 0)

    if changed:
        _save_state(st)


if __name__ == "__main__":
    _log("Ручной запуск integration_alerts (проверка + алерты по переходам)")
    check_and_alert()
    st = _load_state()
    for key, fn, label in CHECKS:
        s = st.get(key) or {}
        _log(f"  {label}: {'OK' if s.get('ok') else 'DOWN'} — {s.get('detail', '?')}")
