#!/usr/bin/env python3
"""
geo_audit.py — сборщик GEO/SEO-метрик для дашборда AUTOMATA-CRM.

Архитектура: повторяет паттерн monitoring_core.py / pagespeed_check.py.
Домены берёт из 10_Clients/*.md (через load_domains_from_clients),
бренды/конкуренты — из frontmatter клиента, чеклисты — из 50_Projects_Wiki/.
Выход: dashboard/public/data/geo.json (как monitoring.json).

Не делает живых API-вызовов AI-провайдеров — берёт готовые отчёты из
reports/geo/ (прогоняются скриптом geo-check.mjs или вручную).

Запуск:
  python3 scripts/geo_audit.py           # пересборка geo.json
  python3 scripts/geo_audit.py --refresh # + импорт свежих отчётов
"""
from sec_guard import guard_open


import os
import sys
import json
import glob
import re
from datetime import datetime

import yaml

# Переиспользуем существующую функцию мониторинга — она уже читает 10_Clients,
# фильтрует archive, нормализует домены.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from monitoring_core import load_domains_from_clients, BASE_PATH

# ─────────────────────────────────────────────────────────────────────────────
# КОНСТАНТЫ (по образцу monitoring_core.py)
# ─────────────────────────────────────────────────────────────────────────────

GEO_JSON = os.path.join(BASE_PATH, "dashboard", "public", "data", "geo.json")
PROJECTS_WIKI_DIR = os.path.join(BASE_PATH, "50_Projects_Wiki")
# Папка с внешними отчётами аудитов (если есть — импортируем)
REPORTS_DIRS = [
    os.path.join(BASE_PATH, "reports", "geo"),
    # отчёты из репозиториев проектов (относительно vault)
    os.path.expanduser("~/Документы/ObsidianVault-CRM/GITACTIVE/AUTOMATASALE2026/reports/geo"),
]


# ─────────────────────────────────────────────────────────────────────────────
# ЗАГРУЗКА/СОХРАНЕНИЕ geo.json (по образцу monitoring_core)
# ─────────────────────────────────────────────────────────────────────────────

def load_geo_data():
    if os.path.exists(GEO_JSON):
        try:
            with guard_open(GEO_JSON, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def save_geo_data(data_list):
    os.makedirs(os.path.dirname(GEO_JSON), exist_ok=True)
    with guard_open(GEO_JSON, "w", encoding="utf-8") as f:
        json.dump(data_list, f, ensure_ascii=False, indent=2)


# ─────────────────────────────────────────────────────────────────────────────
# БРЕНДЫ И КОНКУРЕНТЫ (расширенный frontmatter клиента)
# ─────────────────────────────────────────────────────────────────────────────

def load_brand_config_from_client(domain):
    """
    Читает 10_Clients/<client>.md и извлекает brand/competitors/industry
    из frontmatter (если заданы). Возвращает {} если нет.
    Ожидаемый формат в frontmatter клиента:
        geo:
          brand: "Automata"
          industry: "1С-Битрикс разработка, AI"
          competitors: ["Интаро", "Факт", "InterVolga"]
    """
    domains_map = load_domains_from_clients()
    info = domains_map.get(domain)
    if not info:
        return {}
    client_name = info["client"]
    client_file = os.path.join(BASE_PATH, "10_Clients", f"{client_name}.md")
    if not os.path.exists(client_file):
        return {}
    try:
        with guard_open(client_file, "r", encoding="utf-8") as f:
            content = f.read()
        match = re.search(r"^\s*---\n(.*?)\n---", content, re.DOTALL)
        if not match:
            return {}
        meta = yaml.safe_load(match.group(1)) or {}
        return meta.get("geo", {}) or {}
    except Exception:
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# ЧЕКЛИСТЫ из 50_Projects_Wiki/<slug>-geo-plan.md
# ─────────────────────────────────────────────────────────────────────────────

def load_checklist(domain):
    """
    Читает чеклист GEO-задач из markdown-файла в vault.
    Формат frontmatter:
        domain: automata.sale
        tasks:
          - { id: rating-runeta, name: "Регистрация в Рейтинг Рунета", priority: P0, status: planned }
          - { id: vc-article,   name: "Статья на VC.ru",                 priority: P0, status: done }
    Возвращает список задач или [].
    """
    if not os.path.exists(PROJECTS_WIKI_DIR):
        return []
    # Ищем файл по domain в frontmatter
    for fname in os.listdir(PROJECTS_WIKI_DIR):
        if not fname.endswith(".md") or "geo-plan" not in fname:
            continue
        fpath = os.path.join(PROJECTS_WIKI_DIR, fname)
        try:
            with guard_open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
            match = re.search(r"^\s*---\n(.*?)\n---", content, re.DOTALL)
            if not match:
                continue
            meta = yaml.safe_load(match.group(1)) or {}
            if meta.get("domain") == domain:
                return meta.get("tasks", []) or []
        except Exception:
            continue
    return []


# ─────────────────────────────────────────────────────────────────────────────
# ИМПОРТ ОТЧЁТОВ АУДИТОВ (готовые JSON из reports/geo/)
# ─────────────────────────────────────────────────────────────────────────────

def find_latest_report(domain):
    """
    Ищет свежий отчёт аудита для домена во всех папках reports/geo/.
    Имя файла: geo-<brand-slug>-<дата>.json. Сопоставление по domain в отчёте.
    Возвращает dict отчёта или None.
    """
    candidates = []
    for reports_dir in REPORTS_DIRS:
        if not os.path.isdir(reports_dir):
            continue
        for fpath in glob.glob(os.path.join(reports_dir, "geo-*.json")):
            try:
                with guard_open(fpath, "r", encoding="utf-8") as f:
                    report = json.load(f)
                # Сопоставляем по url/domain в отчёте
                report_domain = (report.get("url") or "").replace("https://", "").replace("http://", "").split("/")[0]
                if report_domain == domain:
                    candidates.append((os.path.getmtime(fpath), report, fpath))
            except Exception:
                continue
    if not candidates:
        return None
    # Самый свежий
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def extract_metrics_from_report(report):
    """
    Извлекает метрики из отчёта geo-check (формат FireGEO/geo-check.mjs).
    Возвращает dict с ключами для geo.json.
    """
    scores = report.get("scores", {})
    results = report.get("results", [])

    # Честная видимость (только сторонние упоминания)
    honest_visibility = scores.get("honestVisibility", scores.get("visibilityScore", 0))
    honest_sov = scores.get("honestShareOfVoice", scores.get("shareOfVoice", 0))

    # Где упоминается бренд
    mentioned_results = [r for r in results if r.get("detection", {}).get("mentioned")]

    # Топ-конкуренты из results[].competitorsFound
    comp_counter = {}
    for r in results:
        for c in (r.get("competitorsFound") or []):
            comp_counter[c] = comp_counter.get(c, 0) + 1
    top_competitors = sorted(comp_counter.items(), key=lambda x: x[1], reverse=True)[:8]

    return {
        "visibilityScore": scores.get("visibilityScore", 0),
        "honestVisibility": honest_visibility,
        "shareOfVoice": scores.get("shareOfVoice", 0),
        "honestShareOfVoice": honest_sov,
        "overallScore": scores.get("overallScore", 0),
        "promptsAnalyzed": report.get("promptsAnalyzed", len(results)),
        "providersUsed": report.get("providersUsed", []),
        "mentionedCount": len(mentioned_results),
        "thirdPartyMentioned": sum(
            1 for r in mentioned_results
            if r.get("detection", {}).get("note")
            and "собственн" not in r["detection"]["note"].lower()
        ),
        "topCompetitors": [{"name": n, "mentions": m} for n, m in top_competitors],
        "analyzedAt": report.get("analyzedAt"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# СИНХРОНИЗАЦИЯ (по образцу sync_domains_with_monitoring)
# ─────────────────────────────────────────────────────────────────────────────

def load_domains_from_geo_plans():
    """
    Читает домены из 50_Projects_Wiki/*-geo-plan.md (собственные проекты,
    не клиенты). Возвращает dict как load_domains_from_clients.
    """
    result = {}
    if not os.path.exists(PROJECTS_WIKI_DIR):
        return result
    for fname in os.listdir(PROJECTS_WIKI_DIR):
        if not fname.endswith(".md") or "geo-plan" not in fname:
            continue
        fpath = os.path.join(PROJECTS_WIKI_DIR, fname)
        try:
            with guard_open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
            match = re.search(r"^\s*---\n(.*?)\n---", content, re.DOTALL)
            if not match:
                continue
            meta = yaml.safe_load(match.group(1)) or {}
            domain = meta.get("domain")
            if not domain:
                continue
            clean = str(domain).replace("https://", "").replace("http://", "").split("/")[0].strip()
            if clean:
                brand = meta.get("brand", clean.split(".")[0].capitalize())
                result[clean] = {
                    "client": f"{brand} (проект)",
                    "url": f"https://{clean}",
                    "domain": clean,
                    "brand": brand,
                }
        except Exception:
            continue
    return result


def get_all_geo_domains():
    """
    Объединяет домены клиентов (10_Clients) и собственных проектов
    (50_Projects_Wiki/*-geo-plan.md). Клиенты имеют приоритет при конфликте.
    """
    domains = load_domains_from_geo_plans()
    client_domains = load_domains_from_clients()
    domains.update(client_domains)  # клиенты перетирают проекты при совпадении
    return domains


def sync_domains_with_geo(refresh=False):
    """
    Мержит текущие домены (клиенты + проекты) с уже сохранённым geo.json.
    Если refresh=True — подтягивает свежие отчёты из reports/geo/.
    """
    actual_domains = get_all_geo_domains()
    existing_data = load_geo_data()
    existing_map = {item["domain"]: item for item in existing_data if "domain" in item}

    synced_list = []
    for dom, info in actual_domains.items():
        # Базовая запись (новая или существующая)
        if dom in existing_map:
            entry = existing_map[dom]
            entry["name"] = info["client"]
            entry["url"] = info["url"]
        else:
            entry = {
                "name": info["client"],
                "url": info["url"],
                "domain": dom,
                "brand": info.get("brand", info["client"]),
                "visibilityScore": None,
                "honestVisibility": None,
                "shareOfVoice": None,
                "overallScore": None,
                "promptsAnalyzed": 0,
                "topCompetitors": [],
                "checklist": [],
                "lastChecked": None,
            }

        # Достаём бренд/конкурентов из frontmatter клиента
        brand_cfg = load_brand_config_from_client(dom)
        if brand_cfg.get("brand"):
            entry["brand"] = brand_cfg["brand"]
        if brand_cfg.get("industry"):
            entry["industry"] = brand_cfg["industry"]
        if brand_cfg.get("competitors"):
            entry["competitors"] = brand_cfg["competitors"]

        # Чеклист из markdown
        entry["checklist"] = load_checklist(dom)

        # Свежий отчёт (если refresh)
        if refresh:
            report = find_latest_report(dom)
            if report:
                metrics = extract_metrics_from_report(report)
                entry.update(metrics)
                entry["lastChecked"] = metrics.get("analyzedAt") or datetime.utcnow().isoformat() + "Z"

        synced_list.append(entry)

    return synced_list


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    refresh = "--refresh" in sys.argv
    action = "пересборка + импорт отчётов" if refresh else "пересборка (без импорта)"
    print(f"📊 GEO-аудит: {action}")

    data = sync_domains_with_geo(refresh=refresh)
    save_geo_data(data)

    # Краткая сводка
    with_reports = [d for d in data if d.get("overallScore") is not None]
    with_checklist = [d for d in data if d.get("checklist")]
    print(f"   Доменов: {len(data)}")
    print(f"   С метриками аудита: {len(with_reports)}")
    print(f"   С чеклистами: {len(with_checklist)}")
    for d in data:
        score = d.get("overallScore")
        checklist = d.get("checklist", [])
        done = sum(1 for t in checklist if t.get("status") == "done")
        print(f"   • {d['domain']:30} vis={d.get('honestVisibility', '—')}%  score={score if score is not None else '—'}  чеклист: {done}/{len(checklist)}")
    print(f"\n✓ Сохранено: {GEO_JSON}")


if __name__ == "__main__":
    main()
