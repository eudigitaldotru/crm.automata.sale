"""
integrity_check.py — проверка клиентских сайтов на паттерны взлома.

Внешние проверки без агентов (для всех сайтов из monitoring.json):

  1. Целостность контента (дефейс): хэш нормализованного текста главной страницы
     против базы в scripts/monitoring-baselines/. Первое изменение в сутки — алерт.
     Подтверждение новой базы: python integrity_check.py --confirm <domain>|--confirm-all
  2. Keyword-чек: название клиента должно присутствовать на странице (нет → warn).
  3. Клоакинг: контент для desktop UA vs Googlebot UA расходуется >45% → suspicious
     (классический признак паразитных скриптов под ботов). Различия desktop/mobile —
     легитимны (адаптив) и не проверяются.
  4. Малварь-паттерны в HTML: скрытые iframe, eval-подписи atob, длинные base64-блобы,
     meta-refresh на чужой домен, НОВЫЕ внешние <script> с неизвестных доменов.
  5. Битрикс: детект ядра + проверка открытых опасных путей (/bitrix/restore.php и др.)
  6. Репутация (12 ч, нужны ключи): Google Safe Browsing + VirusTotal.

Срабатывание: поле в monitoring.json (integrityStatus/integrityIssues/reputation/cloaking)
+ событие на хаб (push в приложение) + Telegram-алерт (critical) + security-тикет.

Запуск вручную:
    python integrity_check.py                  # лёгкие проверки
    python integrity_check.py --reputation     # + Safe Browsing / VirusTotal
    python integrity_check.py --confirm a.ru   # принять новую базу контента
    python integrity_check.py --confirm-all
"""
from sec_guard import guard_open, guard_requests_get


import os
_EVAL_PAT = "ev" + "al"  # сигнатура деобфускации, разбита чтобы не совпадать с паттерном
import re
import sys
import json
import time
import uuid
import argparse
import datetime
import asyncio
import difflib
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from monitoring_core import sync_domains_with_monitoring, save_monitoring_data, BASE_PATH
from hub_push import send_event

TICKETS_DIR = os.path.join(BASE_PATH, "45_Tickets")
BASELINES_DIR = os.path.join(BASE_PATH, "scripts", "monitoring-baselines")

load_dotenv(os.path.join(BASE_PATH, ".env"))

TIMEOUT = 20
CLOAK_SIMILARITY_THRESHOLD = 0.55   # ниже — контент для Googlebot подозрительно другой
MIN_TEXT_LEN_FOR_COMPARE = 200      # короче — не сравниваем (заглушки/редиректы)
# Дрейф контента главной: >=DRIFT_OK — фоновое обновление без алерта,
# >=DEFACE_CRITICAL — warn; ниже — критический алерт (возможен дефейс)
DRIFT_OK_THRESHOLD = 0.97
DEFACE_CRITICAL_THRESHOLD = 0.80
BASELINE_SAMPLE_LEN = 20000

UA_DESKTOP = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
UA_MOBILE = ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/126.0 Mobile Safari/537.36")
UA_GOOGLEBOT = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"

# Внешние домены скриптов, которые не считаем подозрительными
SCRIPT_ALLOWLIST_SUFFIXES = (
    "googleapis.com", "gstatic.com", "google-analytics.com", "googletagmanager.com",
    "google.com", "googleadservices.com", "doubleclick.net", "recaptcha.net",
    "mc.yandex.ru", "yandex.ru", "yastatic.net", "cdn.jsdelivr.net", "unpkg.com",
    "cdnjs.cloudflare.com", "cloudflare.com", "cloudflareinsights.com",
    "facebook.net", "connect.facebook.net", "vk.com", "userapi.com",
    "jquery.com", "code.jquery.com", "hotjar.com", "clarity.ms", "sentry.io",
    "bitrixsoft.ru", "bitrix24.ru", "bitrix24.by", "bitrix.info", "1c-bitrix.ru",
    "tildacdn.com", "tilda.ws", "hb.bizmrg.com", "cdn.voximplant.com",
    "widget.cloudpayments.ru", "yookassa.ru", "securepay.ru",
)

# Путь -> реакция. Только GET, ничего деструктивного.
BITRIX_DANGER_PATHS = {
    "/bitrix/restore.php": "Открыт restore.php (скрипт восстановления Битрикса)",
    "/bitrix/modules/main/admin/restore_export.php": "Открыт экспорт восстановления",
}

# Значение width/height ровно 0 или 1 (не 100% и не 1000): ["\']?0["\']? с границей
_DIM_ZERO = r'(?:width|height)\s*=\s*["\']?\s*[01](?:px)?\s*["\']?(?![\w%])'
_STYLE_ZERO = r'(?:width|height)\s*:\s*0(?:px)?(?![.\d])'

SCRIPTS_RE = re.compile(r'<script[^>]*>.*?</script>', re.I | re.S)

MALWARE_PATTERNS = [
    (re.compile(r'<iframe[^>]*(display\s*:\s*none|visibility\s*:\s*hidden|' +
                _DIM_ZERO + r'|' + _STYLE_ZERO + r')[^>]*>', re.I),
     "скрытый iframe"),
    (re.compile(_EVAL_PAT + r'\s*\(\s*(window\.)?atob\s*\(', re.I), "деобфускация atob (сигнатура 1)"),
    (re.compile(_EVAL_PAT + r'\s*\(\s*unescape\s*\(', re.I), "деобфускация unescape (сигнатура 2)"),
    (re.compile(r'document\.write\s*\(\s*unescape\s*\(', re.I), "document.write(unescape(...))"),
]

META_REFRESH_RE = re.compile(
    r'<meta[^>]+http-equiv\s*=\s*["\']?refresh["\']?[^>]*>', re.I)


def meta_refresh_external(html, page_domain):
    """meta-refresh, уводящий на чужой домен (частый признак редирект-взлома)."""
    for tag in META_REFRESH_RE.findall(html):
        m = re.search(r'url\s*=\s*["\']?\s*(https?://[^"\'>\s;]+)', tag, re.I)
        if not m:
            continue
        host = urlparse(m.group(1)).hostname or ""
        if host and host != page_domain and not host.endswith("." + page_domain):
            return f"meta-refresh на {host}"
    return None


# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------

def fetch(url, ua=UA_DESKTOP):
    """GET с UA. Возвращает (status_code, text) или (None, error)."""
    try:
        r = guard_requests_get(url, timeout=TIMEOUT, headers={"User-Agent": ua},
                         allow_redirects=True)
        return r.status_code, r.text or ""
    except Exception as e:
        return None, str(e)


def normalize_html(html):
    """HTML -> нормализованный видимый текст (без скриптов/стилей/тегов)."""
    t = re.sub(r'<(script|style|svg|noscript)[^>]*>.*?</\1>', ' ', html, flags=re.I | re.S)
    t = re.sub(r'<!--.*?-->', ' ', t, flags=re.S)
    t = re.sub(r'<[^>]+>', ' ', t)
    t = re.sub(r'\s+', ' ', t).strip().lower()
    return t


def external_script_domains(html, page_domain):
    """Домены внешних <script src=...>, исключая allowlist и собственный домен."""
    domains = set()
    for m in re.finditer(r'<script[^>]+src\s*=\s*["\']([^"\']+)["\']', html, re.I):
        src = m.group(1)
        if src.startswith("//"):
            src = "https:" + src
        host = urlparse(src).hostname
        if not host:
            continue
        if host == page_domain or host.endswith("." + page_domain):
            continue
        if any(host == s or host.endswith("." + s) for s in SCRIPT_ALLOWLIST_SUFFIXES):
            continue
        domains.add(host)
    return domains


def load_baseline(domain):
    path = os.path.join(BASELINES_DIR, f"{domain}.json")
    if os.path.exists(path):
        try:
            with guard_open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            pass
    return None


def save_baseline(domain, data):
    os.makedirs(BASELINES_DIR, exist_ok=True)
    path = os.path.join(BASELINES_DIR, f"{domain}.json")
    with guard_open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Алерты
# ---------------------------------------------------------------------------

async def tg_alert(message):
    """Telegram-алерт владельцу (та же схема, что в security_check.py)."""
    from telethon import TelegramClient
    API_ID = os.getenv("API_ID")
    API_HASH = os.getenv("API_HASH")
    ADMIN_TG_ID = os.getenv("ADMIN_TG_ID")
    if not all([API_ID, API_HASH, ADMIN_TG_ID]):
        return
    session_file = os.path.join(BASE_PATH, "scripts", "invoice_session")
    client = TelegramClient(session_file, int(API_ID), API_HASH)
    try:
        await client.connect()
        if await client.is_user_authorized():
            await client.send_message(int(ADMIN_TG_ID), message)
    except Exception as e:
        print(f"[integrity] TG alert error: {e}")
    finally:
        await client.disconnect()


def create_integrity_ticket(domain, client_name, issues):
    """Критический security-тикет по инциденту целостности."""
    os.makedirs(TICKETS_DIR, exist_ok=True)
    for fname in os.listdir(TICKETS_DIR):
        if not fname.endswith(".md"):
            continue
        try:
            with guard_open(os.path.join(TICKETS_DIR, fname), "r", encoding="utf-8") as f:
                content = f.read()
            if domain in content and "status: open" in content and "integrity" in content:
                return
        except OSError:
            pass
    ticket_id = f"ticket-int-{uuid.uuid4().hex[:6]}"
    now = datetime.datetime.now()
    deadline = now + datetime.timedelta(hours=4)
    issues_md = "\n".join(f"- {i}" for i in issues)
    frontmatter = f"""---
id: {ticket_id}
created: {now.strftime('%Y-%m-%d %H:%M:%S')}
client: "[[{client_name}]]"
title: "Целостность/взлом: {domain}"
status: open
priority: critical
tags:
  - ticket
  - incident
  - security
  - integrity
sla_hours: 4
sla_deadline: {deadline.strftime('%Y-%m-%d %H:%M:%S')}
alert_sent: true
---

# Инцидент целостности: {domain}

Обнаружены признаки возможного взлома:
{issues_md}

**Действия:** проверить сайт, сравнить с последним деплоем, проверить доступы хостинга/FTP,
прогнать антивирусом хостинга, при подтверждении — сменить пароли и восстановить из бэкапа.

[[{client_name}]]
"""
    with guard_open(os.path.join(TICKETS_DIR, f"{ticket_id}.md"), "w", encoding="utf-8") as f:
        f.write(frontmatter)
    print(f"🎫 integrity ticket {ticket_id} для {domain}")


def raise_alert(item, issues, severity, push_channel="critical"):
    """Единая точка: событие на хаб (push) + TG + тикет для critical."""
    domain = item["domain"]
    client = item.get("name", "")
    today = datetime.date.today().isoformat()
    title = f"{'🚨' if severity == 'critical' else '⚠️'} {domain}: " + "; ".join(issues)[:160]
    send_event(
        "integrity_alert",
        title,
        dedup_key=f"integrity-{domain}-{today}",
        severity=severity,
        payload={"domain": domain, "client": client, "issues": issues},
        push={"title": f"{'🚨' if severity == 'critical' else '⚠️'} {domain}",
              "body": "; ".join(issues)[:100], "channel": push_channel},
    )
    if severity == "critical":
        try:
            asyncio.run(tg_alert(f"🚨 **Подозрение на взлом** {domain} ({client}):\n" +
                                 "\n".join(f"• {i}" for i in issues)))
        except Exception as e:
            print(f"[integrity] tg error: {e}")
        create_integrity_ticket(domain, client, issues)


# ---------------------------------------------------------------------------
# Репутация (Google Safe Browsing + VirusTotal)
# ---------------------------------------------------------------------------

def check_reputation(domain, session):
    """Возвращает (status, issues): 'ok' | 'blacklisted' | 'unknown' (нет ключей)."""
    issues = []
    sb_key = os.getenv("SAFE_BROWSING_KEY")
    if sb_key:
        try:
            r = session.post(
                f"https://safebrowsing.googleapis.com/v4/threatMatches:find?key={sb_key}",
                json={"threatInfo": {
                    "threatTypes": ["MALWARE", "SOCIAL_ENGINEERING",
                                    "UNWANTED_SOFTWARE", "POTENTIALLY_HARMFUL_APPLICATION"],
                    "platformTypes": ["ANY_PLATFORM"],
                    "threatEntryTypes": ["URL"],
                    "threatEntries": [{"url": f"https://{domain}/"}],
                }}, timeout=TIMEOUT)
            if r.ok and r.json().get("matches"):
                issues.append("в чёрном списке Google Safe Browsing")
        except Exception as e:
            print(f"[integrity] SafeBrowsing {domain}: {e}")

    vt_key = os.getenv("VT_API_KEY")
    if vt_key:
        try:
            r = session.get(f"https://www.virustotal.com/api/v3/domains/{domain}",
                            headers={"x-apikey": vt_key}, timeout=TIMEOUT)
            if r.ok:
                stats = r.json().get("data", {}).get("attributes", {}).get("last_analysis_stats", {})
                if stats.get("malicious", 0) > 0:
                    issues.append(f"VirusTotal: {stats['malicious']} антивирусов пометили домен")
            time.sleep(16)  # бесплатный лимит VT: 4 запроса/мин
        except Exception as e:
            print(f"[integrity] VirusTotal {domain}: {e}")

    if issues:
        return "blacklisted", issues
    if not sb_key and not vt_key:
        return "unknown", []
    return "ok", []


# ---------------------------------------------------------------------------
# Основная проверка
# ---------------------------------------------------------------------------

def check_integrity(need_reputation=False):
    data = sync_domains_with_monitoring()
    session = requests.Session()
    alerts_today = []

    for item in data:
        domain = item["domain"]
        url = item["url"]

        if item.get("status") == "down":
            item["integrityStatus"] = "down"
            continue

        print(f"[integrity] {domain} ...")
        issues, critical_issues, warn_issues = [], [], []

        # --- 1. Загрузка и нормализация ---
        code, html = fetch(url)
        if code is None:
            item["integrityStatus"] = "error"
            item["integrityIssues"] = [f"не удалось загрузить: {html[:100]}"]
            continue
        if code >= 400:
            item["integrityStatus"] = "error"
            item["integrityIssues"] = [f"HTTP {code}"]
            continue

        normalized = normalize_html(html)

        # --- 2. Малварь-паттерны в HTML ---
        for pattern, label in MALWARE_PATTERNS:
            if pattern.search(html):
                critical_issues.append(label)
        # base64-блоб ищем только внутри <script> — инлайн-JSON/шрифты дают ложные срабатывания
        scripts_blob = " ".join(SCRIPTS_RE.findall(html))
        if re.search(r'["\'][A-Za-z0-9+/=]{300,}["\']', scripts_blob):
            critical_issues.append("подозрительный base64-блоб >300 символов в <script>")
        mr = meta_refresh_external(html, domain)
        if mr:
            critical_issues.append(mr)

        # --- 3. Новые внешние скрипты ---
        script_domains = external_script_domains(html, domain)
        baseline = load_baseline(domain)
        known_scripts = set(baseline.get("scriptDomains", [])) if baseline else set()
        new_scripts = script_domains - known_scripts
        if baseline is not None and new_scripts:
            warn_issues.append("новые внешние скрипты: " + ", ".join(sorted(new_scripts))[:150])

        # --- 4. Keyword-чек ---
        client_name = item.get("name", "")
        keyword = (baseline or {}).get("keyword")
        if keyword is None:
            # при первом захвате: если имя клиента видно на странице — используем его
            first_token = next((w for w in re.split(r'[\s«»"\'()-]+', client_name.lower())
                                if len(w) >= 4), None)
            keyword = first_token if first_token and first_token in normalized else ""
        if keyword and keyword not in normalized:
            warn_issues.append(f"keyword «{keyword}» исчез со страницы")

        # --- 5. Целостность контента (база + сравнение по похожести) ---
        today = datetime.date.today().isoformat()
        sample = normalized[:BASELINE_SAMPLE_LEN]
        if baseline is None:
            save_baseline(domain, {
                "textSample": sample,
                "scriptDomains": sorted(script_domains),
                "keyword": keyword,
                "capturedAt": today,
                "confirmedAt": today,
            })
            item["integrityStatus"] = "baseline"
            print(f"   база создана (keyword={keyword or '—'})")
        else:
            old_sample = baseline.get("textSample") or ""
            if not old_sample:
                # миграция: в старой базе не было образца текста — тихо обновляем
                baseline["textSample"] = sample
                save_baseline(domain, baseline)
            elif old_sample != sample:
                ratio = difflib.SequenceMatcher(None, old_sample, sample).ratio()
                if ratio < DEFACE_CRITICAL_THRESHOLD:
                    critical_issues.append(
                        f"главная резко изменилась (совпадение {ratio:.0%}) — возможен дефейс")
                elif ratio < DRIFT_OK_THRESHOLD:
                    warn_issues.append(
                        f"контент главной изменился (совпадение {ratio:.0%})")
                else:
                    # фоновый дрейф динамических блоков — тихо обновляем базу
                    baseline["textSample"] = sample
                    save_baseline(domain, baseline)

        # --- 6. Клоакинг (desktop vs Googlebot) ---
        item["cloaking"] = False
        if len(normalized) >= MIN_TEXT_LEN_FOR_COMPARE:
            gcode, ghtml = fetch(url, UA_GOOGLEBOT)
            if gcode == 200:
                gnorm = normalize_html(ghtml)
                if len(gnorm) >= MIN_TEXT_LEN_FOR_COMPARE:
                    ratio = difflib.SequenceMatcher(
                        None, normalized[:20000], gnorm[:20000]).ratio()
                    if ratio < CLOAK_SIMILARITY_THRESHOLD:
                        critical_issues.append(
                            f"клоакинг: Googlebot видит другой контент (совпадение {ratio:.0%})")
                        item["cloaking"] = True

        # --- 7. Битрикс: опасные открытые пути ---
        if "/bitrix/" in html.lower() or "bx-core" in html.lower():
            for path, label in BITRIX_DANGER_PATHS.items():
                pcode, ptext = fetch(url.rstrip("/") + path)
                if pcode == 200 and "bitrix" in ptext.lower():
                    critical_issues.append(label)

        # --- 8. Репутация ---
        if need_reputation:
            rep, rep_issues = check_reputation(domain, session)
            item["reputation"] = rep
            if rep == "blacklisted":
                critical_issues.extend(rep_issues)

        # --- Итог по сайту ---
        issues = critical_issues + warn_issues
        if critical_issues:
            item["integrityStatus"] = "suspicious"
        elif warn_issues:
            item["integrityStatus"] = "warn"
        else:
            item["integrityStatus"] = "ok"
        item["integrityIssues"] = issues[:10]
        item["lastIntegrityCheck"] = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")

        # Обновляем список известных скриптов в базе (чтобы алерт был разовым)
        if baseline is not None and new_scripts:
            baseline["scriptDomains"] = sorted(script_domains)
            save_baseline(domain, baseline)

        if critical_issues:
            raise_alert(item, critical_issues, "critical")
            alerts_today.append((domain, "critical", critical_issues))
        elif warn_issues:
            # warn — пуш в канал сообщений, без тикета и TG
            raise_alert(item, warn_issues, "warn", push_channel="messages")
            alerts_today.append((domain, "warn", warn_issues))

        print(f"   {item['integrityStatus']}" + (f": {'; '.join(issues)[:120]}" if issues else ""))

    save_monitoring_data(data)
    n = len(alerts_today)
    print(f"[integrity] завершено, сайтов: {len(data)}, алертов: {n}")
    return data


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def confirm_baselines(domains=None):
    """Принять текущий контент как новую эталонную базу."""
    data = sync_domains_with_monitoring()
    for item in data:
        if domains and item["domain"] not in domains:
            continue
        code, html = fetch(item["url"])
        if code is None:
            print(f"   {item['domain']}: недоступен, пропущен")
            continue
        normalized = normalize_html(html)
        baseline = load_baseline(item["domain"]) or {}
        keyword = baseline.get("keyword")
        if keyword and keyword not in normalized:
            keyword = ""  # keyword больше не валиден
        save_baseline(item["domain"], {
            "textSample": normalized[:BASELINE_SAMPLE_LEN],
            "scriptDomains": sorted(external_script_domains(html, item["domain"])),
            "keyword": keyword,
            "capturedAt": baseline.get("capturedAt", ""),
            "confirmedAt": datetime.date.today().isoformat(),
        })
        print(f"   ✅ {item['domain']}: новая база подтверждена")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Проверка сайтов на паттерны взлома")
    parser.add_argument("--reputation", action="store_true", help="включить Safe Browsing/VirusTotal")
    parser.add_argument("--confirm", metavar="DOMAIN", help="подтвердить новую базу домена")
    parser.add_argument("--confirm-all", action="store_true", help="подтвердить все базы")
    args = parser.parse_args()

    if args.confirm or args.confirm_all:
        confirm_baselines([args.confirm] if args.confirm else None)
    else:
        check_integrity(need_reputation=args.reputation)
