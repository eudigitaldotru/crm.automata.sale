"""
contact_index.py — единый индекс «своих» для входящего конвейера AUTOMATA-CRM.

Собирает из 10_Clients/*.md (карточки клиентов) и 10_Clients/Contacts/*.md
(карточки людей) все идентификаторы и строит карту:

    идентификатор (email / телефон / tg username / tg_id / chat_id группы)
        → клиент + контактное лицо

Результат: scripts/.contact_index.json (runtime-артефакт, в .gitignore).

Используется inbox_triage.py и 2-часовой ZCode-автоматизацией.
Правило конвейера: обрабатываются ТОЛЬКО отправители из этого индекса.

Запуск:
    python3 scripts/contact_index.py           # пересобрать + сводка
    python3 scripts/contact_index.py --json    # тихий JSON на stdout

Формат tg_chats в карточке клиента (привязка рабочих групп, их может быть
несколько):
    tg_chats:
      - id: "-1001234567890"
        title: "Мягкая кровля — сайт"
    или просто:  tg_chats: ["-1001234567890", "-1009876543210"]
"""
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import yaml

BASE = Path(__file__).resolve().parent.parent
CLIENTS_DIR = BASE / "10_Clients"
CONTACTS_DIR = CLIENTS_DIR / "Contacts"
OUT_FILE = Path(__file__).resolve().parent / ".contact_index.json"

USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{3,}$")


def normalize_phone(raw) -> str:
    """'+7 (927) 123-70-15' → '79271237015'; 10 цифр с 9 → добавляем 7."""
    if raw is None:
        return ""
    digits = re.sub(r"\D", "", str(raw))
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    if len(digits) == 10 and digits.startswith("9"):
        digits = "7" + digits
    return digits if len(digits) == 11 else ""


def normalize_username(raw) -> str:
    if not raw:
        return ""
    u = str(raw).strip().lower().lstrip("@")
    return u if USERNAME_RE.match(u) else ""


def normalize_emails(raw):
    """Строка с запятыми или список → set нижнего регистра."""
    out = set()
    if not raw:
        return out
    items = raw if isinstance(raw, list) else str(raw).split(",")
    for e in items:
        e = str(e).strip().lower()
        if "@" in e:
            out.add(e)
    return out


def parse_frontmatter(path: Path):
    try:
        text = path.read_text(encoding="utf-8")
        m = re.match(r"^\s*---\n(.*?)\n---", text, re.DOTALL)
        if not m:
            return {}
        meta = yaml.safe_load(m.group(1))
        return meta if isinstance(meta, dict) else {}
    except Exception:
        return {}


def wikilink_name(val) -> str:
    """'[[Мягкая кровля]]' → 'Мягкая кровля'."""
    m = re.search(r"\[\[([^\]|]+)", str(val or ""))
    return m.group(1).strip() if m else str(val or "").strip()


class Index:
    def __init__(self):
        self.by_email = {}
        self.by_phone = {}
        self.by_username = {}
        self.by_tg_id = {}
        self.by_chat_id = {}
        self.clients = {}
        self.warnings = []

    def _put(self, mapping, key, entry):
        if not key:
            return
        existing = mapping.get(key)
        if existing and existing["client"] != entry["client"]:
            self.warnings.append(
                f"конфликт {key!r}: {existing['client']} и {entry['client']} — "
                f"оставлен первый ({existing['client']})"
            )
            return
        mapping[key] = entry

    def add(self, *, client, contact=None, emails=(), phones=(), usernames=(),
            tg_ids=(), chats=()):
        entry = {"client": client, "contact": contact}
        for e in emails:
            self._put(self.by_email, e, entry)
        for p in phones:
            self._put(self.by_phone, p, entry)
        for u in usernames:
            self._put(self.by_username, u, entry)
        for t in tg_ids:
            self._put(self.by_tg_id, str(t), entry)
        for chat in chats:
            self._put(self.by_chat_id, str(chat["id"]), {
                "client": client, "contact": contact, "chat_title": chat.get("title", "")})

    def to_dict(self):
        return {
            "built_at": datetime.now().isoformat(timespec="seconds"),
            "clients": self.clients,
            "by_email": self.by_email,
            "by_phone": self.by_phone,
            "by_username": self.by_username,
            "by_tg_id": self.by_tg_id,
            "by_chat_id": self.by_chat_id,
            "warnings": self.warnings,
        }


def parse_tg_chats(raw):
    """tg_chats: список id/строк/словарей {id, title} → [{id, title}]."""
    chats = []
    if not raw:
        return chats
    items = raw if isinstance(raw, list) else [raw]
    for it in items:
        if isinstance(it, dict):
            cid = str(it.get("id", "")).strip()
            if cid:
                chats.append({"id": cid, "title": str(it.get("title", "")).strip()})
        else:
            cid = str(it).strip()
            if cid:
                chats.append({"id": cid, "title": ""})
    return chats


def build_index() -> Index:
    idx = Index()

    # --- Карточки клиентов ---
    for f in sorted(CLIENTS_DIR.glob("*.md")):
        meta = parse_frontmatter(f)
        name = f.stem
        emails = normalize_emails(meta.get("email"))
        phones = set(filter(None, [normalize_phone(meta.get(k)) for k in ("phone", "contact_phone")]))
        tg_raw = str(meta.get("telegram") or meta.get("tg") or meta.get("tg_username") or "").strip()
        usernames = set(filter(None, [normalize_username(tg_raw)]))
        if not usernames and tg_raw:
            ph = normalize_phone(tg_raw)
            if ph:
                phones.add(ph)
        tg_ids = set(filter(None, [str(meta.get("tg_id") or "").strip()]))
        chats = parse_tg_chats(meta.get("tg_chats"))
        # Привязанные группы MAX (max_chats) → тот же by_chat_id (канал max)
        for it in parse_tg_chats(meta.get("max_chats")):
            idx.by_chat_id.setdefault(str(it["id"]),
                {"client": name, "contact": None, "chat_title": it.get("title", "") or ""})
        idx.add(client=name, emails=emails, phones=phones, usernames=usernames,
                tg_ids=tg_ids, chats=chats)
        idx.clients[name] = {
            "file": str(f.relative_to(BASE)),
            "contact_name": str(meta.get("contact_name") or "").strip(),
            "tg_chats": chats,
        }

    # --- Карточки людей (10_Clients/Contacts) ---
    for f in sorted(CONTACTS_DIR.glob("*.md")):
        meta = parse_frontmatter(f)
        person = f.stem
        client = wikilink_name(meta.get("company"))
        if not client or client not in idx.clients:
            if client:
                idx.warnings.append(
                    f"контакт «{person}»: компания «{client}» не найдена в 10_Clients")
            continue
        emails = normalize_emails(meta.get("email"))
        # phone может быть строкой с запятыми ("79277720353, +79277720353")
        raw_phones = meta.get("phone")
        phones = set()
        if raw_phones:
            items = raw_phones if isinstance(raw_phones, list) else str(raw_phones).split(",")
            phones = {p for p in (normalize_phone(x) for x in items) if p}
        usernames = set(filter(None, [
            normalize_username(meta.get("telegram") or meta.get("tg") or ""),
            normalize_username(meta.get("username") or ""),
        ]))
        tg_ids = set(filter(None, [str(meta.get("tg_id") or "").strip()]))
        idx.add(client=client, contact=person, emails=emails, phones=phones,
                usernames=usernames, tg_ids=tg_ids)

    return idx


def add_bitrix_contacts(idx: Index):
    """Идентификаторы людей из выгрузки Битрикс24 (только для наших клиентов):
    телефоны/email/tg_id → контакт; TG-группы → by_chat_id."""
    src = Path(__file__).resolve().parent / ".bitrix_contacts.json"
    if not src.exists():
        return
    data = json.loads(src.read_text(encoding="utf-8"))
    for client, d in data.items():
        for ph, name in d.get("phones", {}).items():
            idx.by_phone.setdefault(ph, {"client": client, "contact": name})
        for em, name in d.get("emails", {}).items():
            idx.by_email.setdefault(em, {"client": client, "contact": name})
        for tg, name in d.get("tg", {}).items():
            idx.by_tg_id.setdefault(str(tg), {"client": client, "contact": name})
        for g, name in d.get("chats", {}).items():
            idx.by_chat_id.setdefault(str(g), {"client": client, "contact": None,
                                               "chat_title": ""})


def main():
    idx = build_index()
    add_bitrix_contacts(idx)
    data = idx.to_dict()
    OUT_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    if "--json" in sys.argv:
        print(json.dumps(data, ensure_ascii=False))
        return

    people = sum(1 for v in (list(idx.by_email.values()) + list(idx.by_phone.values())
                             + list(idx.by_username.values()) + list(idx.by_tg_id.values()))
                 if v.get("contact"))
    print(f"✅ Индекс: {OUT_FILE.name}")
    print(f"   Клиентов: {len(idx.clients)} (с карточками людей: {CONTACTS_DIR.name}/)")
    print(f"   Email: {len(idx.by_email)} | Телефонов: {len(idx.by_phone)} | "
          f"TG-username: {len(idx.by_username)} | TG-ID: {len(idx.by_tg_id)}")
    print(f"   Привязанных групп (tg_chats): {len(idx.by_chat_id)}")
    for cid, v in idx.by_chat_id.items():
        print(f"     chat {cid} → {v['client']}" + (f" ({v['chat_title']})" if v["chat_title"] else ""))
    if idx.warnings:
        print(f"⚠️  Предупреждения ({len(idx.warnings)}):")
        for w in idx.warnings:
            print(f"     - {w}")


if __name__ == "__main__":
    main()
