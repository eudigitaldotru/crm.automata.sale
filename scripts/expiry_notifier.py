#!/usr/bin/env python3
"""expiry_notifier.py — уведомления клиентам о скором истечении доменов и SSL.

Источник данных: dashboard/public/data/monitoring.json (обновляется штатным
мониторингом: ssl_check.py / whois_check.py / uptime_check.py).

Пороги: домен ≤14 дней, SSL ≤10 дней. Дедуп: scripts/.expiry_sent.json —
одно уведомление на (домен, вид, горизонт): «14d» при первом входе в окно,
повтор «3d» при ≤3 дней до истечения. Повторные запуски в тот же день молчат.

Канал: email из карточки клиента (10_Clients/*.md, первое поле email:).
Отправка — send_email.py от ассистента, без цен и обещаний работ.

    python3 scripts/expiry_notifier.py --dry   # только показать
    python3 scripts/expiry_notifier.py         # отправить
"""
import json
import re
import subprocess
import sys
import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
MONITORING = BASE / "dashboard" / "public" / "data" / "monitoring.json"
CLIENTS_DIR = BASE / "10_Clients"
SENT_FILE = Path(__file__).resolve().parent / ".expiry_sent.json"

DOMAIN_DAYS = 14   # окно предупреждения по домену
SSL_DAYS = 10      # окно предупреждения по SSL

RU_MONTHS = {1: "января", 2: "февраля", 3: "марта", 4: "апреля", 5: "мая",
             6: "июня", 7: "июля", 8: "августа", 9: "сентября", 10: "октября",
             11: "ноября", 12: "декабря"}


def load_sent():
    try:
        return json.loads(SENT_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_sent(d):
    SENT_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def find_client(domain):
    """Домен → (имя клиента, email) по упоминанию в карточках 10_Clients."""
    base_dom = domain.lstrip("www.")
    for card in sorted(CLIENTS_DIR.glob("*.md")):
        try:
            text = card.read_text(encoding="utf-8")
        except Exception:
            continue
        if base_dom in text:
            m = re.search(r"^email:\s*\"?([^\s\"]+)", text, re.M)
            return card.stem, (m.group(1) if m else "")
    return "", ""


def find_chats(client_name):
    """Клиент → клиентские группы: [(вид, chat_id, title)] из карточки.

    tg_chats: → отправка через локальный шлюз /api/chat/send;
    max_chats: → отправка через send_max.py (прямой chat_id).
    """
    if not client_name:
        return []
    card = CLIENTS_DIR / f"{client_name}.md"
    if not card.exists():
        return []
    text = card.read_text(encoding="utf-8")
    chats = []
    for kind, field in (("tg", "tg_chats:"), ("max", "max_chats:")):
        m = re.search(field + r"\s*\n((?:\s+- .*\n?)+)", text)
        if not m:
            continue
        for line in m.group(1).strip().splitlines():
            mid = re.search(r'id:\s*"?(-?\d+)"?', line)
            if mid:
                title = (re.search(r'title:\s*"?([^"\n]+)"?', line) or [None, ""])[1]
                chats.append((kind, mid.group(1), title.strip()))
    return chats


def send_tg(chat_id, text):
    r = subprocess.run(
        ["curl", "-s", "-X", "POST", "http://127.0.0.1:8001/api/chat/send",
         "-H", "Content-Type: application/json",
         "-d", json.dumps({"chat_id": chat_id, "text": text, "author": "jarvis"},
                          ensure_ascii=False)],
        capture_output=True, text=True, timeout=60)
    return '"ok"' in r.stdout or '"outbox' in r.stdout, r.stdout[:120]


def send_max(chat_id, text):
    tmp = BASE / "20_Outbox" / ".tmp_expiry_max.txt"
    tmp.write_text(text, encoding="utf-8")
    try:
        r = subprocess.run(
            [sys.executable, str(BASE / "scripts" / "send_max.py"), chat_id,
             "--text-file", str(tmp)],
            capture_output=True, text=True, timeout=90)
    finally:
        tmp.unlink(missing_ok=True)
    return "✅" in r.stdout or "mid" in r.stdout, (r.stdout + r.stderr)[:120]


def parse_date(s):
    try:
        return datetime.date.fromisoformat(str(s)[:10])
    except Exception:
        return None


def build_text(kind, domain, till, client_name):
    d = parse_date(till)
    nice = f"{d.day} {RU_MONTHS.get(d.month, '')} {d.year}" if d else str(till)
    what = ("домен " + domain) if kind == "domain" else ("SSL-сертификат сайта " + domain)
    head = (f"Срок действия {what} истекает {nice}."
            if kind == "domain" else
            f"SSL-сертификат сайта {domain} истекает {nice}.")
    if kind == "domain":
        advice = ("Если домен продлевается у вас автоматически — просто проигнорируйте это письмо.\n"
                  "Если нет — рекомендуем продлить домен у регистратора заранее, "
                  "чтобы сайт и почта на домене не остановились.")
    else:
        advice = ("Если сертификат выпущен с автопродлением (Let's Encrypt и др.) — "
                  "он, скорее всего, обновится сам, письмо информационное.\n"
                  "Если продление ручное — рекомендуем обновить сертификат заранее.")
    return f"""Здравствуйте!

Это служебное уведомление от службы поддержки {client_name} (Automata · automata.sale).

{head}

{advice}

Если нужно содействие по продлению — просто ответьте на это письмо, мы поможем.

—
🤖 Automata CRM assist · ИИ-ассистент
""" + os.getenv("CRM_OWNER_SITE", "example.com") + " · " + os.getenv("CRM_OWNER_PHONE", "+7 (000) 000-00-00")


def normalize_sent(sent):
    """Старый формат ключа 'dom:kind:horizon' (email-only) → 'dom:kind:horizon:email'."""
    out = {}
    for k, v in sent.items():
        parts = k.split(":")
        if len(parts) == 3:
            out[k + ":email"] = v
        else:
            out[k] = v
    return out


def main():
    dry = "--dry" in sys.argv
    today = datetime.date.today()
    data = json.loads(MONITORING.read_text(encoding="utf-8"))
    sent = normalize_sent(load_sent())

    # события в окне: (kind, domain, till, days, horizon)
    events = []
    for site in data:
        domain = site.get("domain") or ""
        if not domain:
            continue
        for kind, field, window in (("domain", "domainExpiryDate", DOMAIN_DAYS),
                                    ("ssl", "expiryDate", SSL_DAYS)):
            till = parse_date(site.get(field))
            if not till:
                continue
            days = (till - today).days
            if days < 0 or days > window:
                continue
            horizon = "3d" if days <= 3 else "14d"
            events.append((kind, domain, till, days, horizon))

    any_sent = False
    for kind, domain, till, days, horizon in events:
        client, email = find_client(domain)
        chats = find_chats(client)
        text = build_text(kind, domain, till, client or "сайта")
        kind_ru = "Домен" if kind == "domain" else "SSL"
        subject = f"{kind_ru} {domain} истекает {till.strftime('%d.%m.%Y')} — служебное уведомление"

        # каналы: email + клиентские группы (tg/max) — дедуп на каждый отдельно
        targets = ([("email", email)] if email else []) + \
                  [(f"{c}:{cid}", f"{c.upper()} {cid} {title}") for c, cid, title in chats]
        if not targets:
            print(f"{'[DRY] ' if dry else ''}{kind:6} {domain} → до {till} ({days} дн) | "
                  f"{client or 'КЛИЕНТ НЕ НАЙДЕН'} — нет каналов!")
            continue

        for chan, dest in targets:
            key = f"{domain}:{kind}:{horizon}:{chan}"
            if key in sent:
                continue
            label = dest if chan == "email" else f"группа {dest}"
            print(f"{'[DRY] ' if dry else ''}{kind:6} {domain} → до {till} ({days} дн) | "
                  f"{client} → {label}")
            if dry:
                continue
            ok = False
            if chan == "email":
                tmp = BASE / "20_Outbox" / ".tmp_expiry.txt"
                tmp.write_text(text, encoding="utf-8")
                try:
                    r = subprocess.run(
                        [sys.executable, str(BASE / "scripts" / "send_email.py"),
                         "--to", email, "--subject", subject,
                         "--text-file", str(tmp)],
                        capture_output=True, text=True, timeout=90)
                finally:
                    tmp.unlink(missing_ok=True)
                ok = "✅" in r.stdout
                print(f"   {'✅ отправлено' if ok else '❌ ошибка'}: {label}"
                      + ("" if ok else f" — {(r.stdout + r.stderr)[:120]}"))
            else:
                ok, info = (send_tg(dest.split()[1], text) if chan.startswith("tg:")
                            else send_max(dest.split()[1], text))
                print(f"   {'✅ отправлено' if ok else '❌ ошибка'}: {label}"
                      + ("" if ok else f" — {info}"))
            if ok:
                sent[key] = today.isoformat()
                any_sent = True

    if any_sent:
        save_sent(sent)
    if not any_sent and dry:
        pass


if __name__ == "__main__":
    main()
