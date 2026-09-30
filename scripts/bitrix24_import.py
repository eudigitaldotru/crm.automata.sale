"""
bitrix24_import.py — импорт выгрузки Битрикс24 в AUTOMATA-CRM.

Источники (60_Reference/bitrix24_export/):
  - contacts.csv  — контакты (люди): телефоны, email, Telegram user_id/группы
  - companies.csv — компании: реквизиты (ИНН/ОГРН/КПП/банк/адрес), сайты

Что делает:
  1) Обогащает КАРТОЧКИ СУЩЕСТВУЮЩИХ клиентов реквизитами из companies.csv
     (по нечувствительному совпадению названия; пустые поля не трогает).
  2) Строит scripts/.bitrix_contacts.json — идентификаторы людей, чья компания
     совпадает с клиентом из нашей базы (правило «только свои»):
     телефоны / email / tg_user_id → клиент+контакт; TG-группы → by_chat_id.
     Файл подхватывает contact_index.py.

Запуск: python3 scripts/bitrix24_import.py [--dry-run]
"""
import csv
import json
import re
import sys
from pathlib import Path

import yaml

BASE = Path(__file__).resolve().parent.parent
EXPORT = BASE / "60_Reference" / "bitrix24_export"
CLIENTS = BASE / "10_Clients"
OUT = Path(__file__).resolve().parent / ".bitrix_contacts.json"


def norm(s):
    return re.sub(r"[^\wа-яё]+", "", str(s or "").lower())


def parse_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";", quotechar='"'))


def clean_phones(raw):
    out = set()
    for part in re.split(r"[,;]", str(raw or "")):
        digits = re.sub(r"\D", "", part)
        if len(digits) == 11 and digits.startswith("8"):
            digits = "7" + digits[1:]
        if len(digits) == 10 and digits.startswith("9"):
            digits = "7" + digits
        if len(digits) == 11 and digits.startswith("7") and digits[1] == "9":
            out.add(digits)
    return out


def clean_emails(raw):
    return {e.strip().lower() for e in re.split(r"[,;]", str(raw or "")) if "@" in e}


def tg_ids(raw):
    """'imol|telegram_unlim|13|5850078614|1731, imol|telegram_unlim_group|13|-4006872004|0'
    → users[], groups[]"""
    users, groups = set(), set()
    for part in re.split(r",(?=\s*imol)", str(raw or "")):
        f = part.strip().split("|")
        if len(f) >= 4 and f[0] == "imol" and f[3].lstrip("-").isdigit():
            if f[1] == "telegram_unlim_group" or f[3].startswith("-"):
                groups.add(f[3])
            else:
                users.add(f[3])
    return users, groups


def client_map():
    """Наши клиенты: norm_name → путь карточки."""
    m = {}
    for f in CLIENTS.glob("*.md"):
        m[norm(f.stem)] = f
    return m


def read_fm(path):
    t = path.read_text(encoding="utf-8")
    m = re.match(r"^\s*---\n(.*?)\n---", t, re.DOTALL)
    meta = yaml.safe_load(m.group(1)) if m else {}
    return t, m, (meta if isinstance(meta, dict) else {})


def enrich_companies(dry):
    comps = parse_csv(EXPORT / "companies.csv")
    cmap = client_map()
    aliases = {  # разные написания
        "печьпросто": "печьпросто", "мастинобульдорс": "мастинобульдорс",
    }
    updated = []
    for c in comps:
        title = (c.get("Название компании") or "").strip()
        if not title:
            continue
        key = norm(aliases.get(norm(title), norm(title)))
        f = cmap.get(key)
        if not f:
            continue
        t, m, meta = read_fm(f)
        changed = False
        fields = {
            "inn": c.get("Реквизит (Россия): ИНН") or "",
            "ogrn": c.get("Реквизит (Россия): ОГРН") or c.get("Реквизит (Россия): ОГРНИП") or "",
            "kpp": c.get("Реквизит (Россия): КПП") or "",
            "legal_address": (c.get("Реквизит (Россия): Адрес") or "").replace("\n", ", ")[:200],
            "bank_name": c.get("Банковский реквизит (Россия): Наименование банка") or "",
            "bank_bik": c.get("Банковский реквизит (Россия): БИК") or "",
            "bank_account": c.get("Банковский реквизит (Россия): Расчетный счёт") or "",
            "company_name": c.get("Реквизит (Россия): Полное наименование организации") or "",
        }
        for k, v in fields.items():
            v = str(v).strip().strip('"').replace('"', "'")
            if v and not str(meta.get(k) or "").strip():
                t = re.sub(rf"^{k}:.*$", f"{k}: \"{v[:180]}\"", t, count=1, flags=re.MULTILINE)
                changed = True
        if changed and not dry:
            f.write_text(t, encoding="utf-8")
        if changed:
            updated.append(f.stem)
    return updated


def build_contacts():
    rows = parse_csv(EXPORT / "contacts.csv")
    cmap = client_map()
    data = {}  # client → {phones:{}, emails:{}, tg:{}, chats:{}}
    n_linked = 0
    for r in rows:
        company = (r.get("Компания") or "").strip()
        f = cmap.get(norm(company))
        if not f:
            continue
        client = f.stem
        name = " ".join(filter(None, [r.get("Имя", ""), r.get("Фамилия", "")])).strip()
        if not name:
            continue
        n_linked += 1
        d = data.setdefault(client, {"phones": {}, "emails": {}, "tg": {}, "chats": {}})
        for p in clean_phones(r.get("Рабочий телефон")) | clean_phones(r.get("Мобильный телефон")) | clean_phones(r.get("Другой телефон")) | clean_phones(r.get("Телефон для рассылок")):
            d["phones"].setdefault(p, name)
        for e in clean_emails(r.get("Рабочий e-mail")) | clean_emails(r.get("Частный e-mail")) | clean_emails(r.get("Другой e-mail")) | clean_emails(r.get("E-mail для рассылок")):
            d["emails"].setdefault(e, name)
        users, groups = tg_ids(r.get("Контакт Telegram"))
        u2, g2 = tg_ids(r.get("Контакт Открытая линия"))
        users |= u2; groups |= g2
        for u in users:
            d["tg"].setdefault(u, name)
        for g in groups:
            d["chats"].setdefault(g, name)
    return data, n_linked


def main():
    dry = "--dry-run" in sys.argv
    updated = enrich_companies(dry)
    print(f"📦 Обогащено карточек клиентов реквизитами: {len(updated)}")
    for u in updated:
        print("   •", u)
    data, n_linked = build_contacts()
    total_ids = sum(len(d["phones"]) + len(d["emails"]) + len(d["tg"]) + len(d["chats"]) for d in data.values())
    if not dry:
        OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"👥 Контактов с известными компаниями: {n_linked} → {len(data)} клиентов, "
          f"{total_ids} идентификаторов (телефоны/email/TG) → {OUT.name}")


if __name__ == "__main__":
    main()
