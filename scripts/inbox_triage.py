"""
inbox_triage.py — триаж 20_Inbox: «свой/чужой» + привязка к клиенту.

Детерминированная часть входящего конвейера (без LLM). Для каждого НОВОГО
файла в 20_Inbox/*.md:

  1. Матчит отправителя с индексом «своих» (scripts/.contact_index.json):
     tg_id → username → телефон → email → chat_id группы (tg_chats клиента).
  2. При матче дописывает/проверяет `client:` во frontmatter файла.
  3. Чужие (не в индексе) НЕ изменяет и НЕ обрабатывает — только строка в отчёте.

Отчёт (stdout) читает ZCode-автоматизация «разбор входящих»: для matched она
делает LLM-часть (контекст клиента, задачи, счета, черновик ответа).

Состояние: scripts/.inbox_triage_state.json (обработанные имена файлов).

Запуск:
    python3 scripts/inbox_triage.py             # только новые файлы
    python3 scripts/inbox_triage.py --all       # все файлы заново
    python3 scripts/inbox_triage.py --json      # машинный отчёт
    python3 scripts/inbox_triage.py --dry-run   # без записи в файлы
"""
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import yaml

BASE = Path(__file__).resolve().parent.parent
INBOX_DIR = BASE / "20_Inbox"
INDEX_FILE = Path(__file__).resolve().parent / ".contact_index.json"
STATE_FILE = Path(__file__).resolve().parent / ".inbox_triage_state.json"


def load_index() -> dict:
    if not INDEX_FILE.exists():
        print("❌ Нет индекса — сначала: python3 scripts/contact_index.py", file=sys.stderr)
        sys.exit(1)
    return json.loads(INDEX_FILE.read_text(encoding="utf-8"))


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"processed": {}}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def parse_frontmatter_text(text):
    m = re.match(r"^\s*---\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return None, text
    try:
        meta = yaml.safe_load(m.group(1))
        if isinstance(meta, dict):
            return meta, text
    except Exception:
        pass
    # Fallback: YAML мог не спарситься (например, вложенные кавычки в subject) —
    # читаем построчно "ключ: значение".
    meta = {}
    for line in m.group(1).splitlines():
        km = re.match(r"^([A-Za-z_][\w]*)\s*:\s*(.*)$", line)
        if km:
            val = km.group(2).strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                val = val[1:-1]
            meta[km.group(1)] = val
    return meta, text


def strip_wikilink(val) -> str:
    m = re.search(r"\[\[([^\]|]+)", str(val or ""))
    return (m.group(1) if m else str(val or "")).strip()


def match_message(meta, index) -> dict:
    """Возвращает {client, contact?, via} или {}."""
    def hit(mapping, key):
        if key and key in mapping:
            e = dict(mapping[key])
            e["via"] = key
            return e
        return None

    tg_id = str(meta.get("tg_id") or "").strip()
    username = str(meta.get("username") or "").strip().lower().lstrip("@")
    sender = str(meta.get("sender") or "").strip()
    phone = re.sub(r"\D", "", str(meta.get("phone") or ""))
    if len(phone) == 11 and phone.startswith("8"):
        phone = "7" + phone[1:]
    email = sender.lower() if "@" in sender else str(meta.get("email") or "").strip().lower()
    chat_id = str(meta.get("chat_id") or "").strip()

    return (hit(index["by_tg_id"], tg_id)
            or hit(index["by_username"], username)
            or hit(index["by_phone"], phone)
            or hit(index["by_email"], email)
            or hit(index["by_chat_id"], chat_id)
            or {})


def set_client_in_file(path: Path, client: str):
    """Дописывает/обновляет client: во frontmatter (in place)."""
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^(\s*---\n)(.*?)(\n---)", text, re.DOTALL)
    if not m:
        return
    fm = m.group(2)
    line = f'client: "[[{client}]]"'
    if re.search(r"^client:", fm, re.MULTILINE):
        fm = re.sub(r"^client:.*$", line, fm, flags=re.MULTILINE)
    else:
        fm = fm + "\n" + line
    path.write_text(m.group(1) + fm + m.group(3) + text[m.end():], encoding="utf-8")


def main():
    args = sys.argv[1:]
    as_json = "--json" in args
    dry_run = "--dry-run" in args
    force_all = "--all" in args

    index = load_index()
    state = load_state()
    processed = state.get("processed", {})

    report = {"ran_at": datetime.now().isoformat(timespec="seconds"),
              "matched": [], "unknown": [], "already": [], "no_frontmatter": []}

    files = sorted(INBOX_DIR.glob("*.md")) if INBOX_DIR.exists() else []
    for f in files:
        fname = f.name
        if not force_all and fname in processed:
            continue

        meta, _ = parse_frontmatter_text(f.read_text(encoding="utf-8"))
        if meta is None:
            report["no_frontmatter"].append(fname)
            processed[fname] = {"ts": report["ran_at"], "result": "no_frontmatter"}
            continue

        existing_client = strip_wikilink(meta.get("client"))
        match = match_message(meta, index)

        if match:
            client = match["client"]
            item = {
                "file": fname,
                "client": client,
                "contact": match.get("contact") or "",
                "via": match["via"],
                "source": meta.get("source") or "",
                "sender": str(meta.get("sender") or ""),
                "subject": str(meta.get("subject") or "")[:120],
            }
            if existing_client and existing_client != client:
                item["note"] = f"в файле был client={existing_client!r}, индекс говорит {client!r}"
            if not existing_client and not dry_run:
                set_client_in_file(f, client)
            report["matched"].append(item)
            processed[fname] = {"ts": report["ran_at"], "result": "matched",
                                "client": client}
        elif existing_client:
            # Клиент уже проставлен (например, gateway-мэтчингом) — считаем своим.
            report["already"].append({"file": fname, "client": existing_client,
                                      "source": meta.get("source") or "",
                                      "sender": str(meta.get("sender") or ""),
                                      "subject": str(meta.get("subject") or "")[:120]})
            processed[fname] = {"ts": report["ran_at"], "result": "already",
                                "client": existing_client}
        else:
            report["unknown"].append({
                "file": fname,
                "sender": str(meta.get("sender") or ""),
                "source": meta.get("source") or "",
                "chat": str(meta.get("chat") or ""),
            })
            processed[fname] = {"ts": report["ran_at"], "result": "unknown"}

    if not dry_run:
        state["processed"] = processed
        state["last_ran_at"] = report["ran_at"]
        save_state(state)

    if as_json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        print(f"🔎 Триаж 20_Inbox ({report['ran_at']})")
        print(f"   Свои (новые, нуждаются в разборе): {len(report['matched'])}")
        for it in report["matched"]:
            who = f" / {it['contact']}" if it["contact"] else ""
            subj = f" — {it['subject']}" if it["subject"] else ""
            print(f"   ✅ {it['file']} → {it['client']}{who} (по {it['via']}){subj}")
            if "note" in it:
                print(f"      ⚠️ {it['note']}")
        print(f"   Свои (client проставлен ранее): {len(report['already'])}")
        for it in report["already"]:
            print(f"   ✔️  {it['file']} → {it['client']}")
        print(f"   Чужие (игнорируем, не в базе): {len(report['unknown'])}")
        for it in report["unknown"]:
            print(f"   ⏭️  {it['file']} — {it['sender'] or it['chat']}")
        if report["no_frontmatter"]:
            print(f"   Без frontmatter: {len(report['no_frontmatter'])} "
                  f"({', '.join(report['no_frontmatter'][:5])})")


if __name__ == "__main__":
    main()
