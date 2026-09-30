"""
chat_projection.py — SQLite-проекция единой ленты коммуникаций поверх md-файлов.

Источник истины — 20_Inbox/ и 20_Outbox/ (md). Этот скрипт строит из них
быстрый индекс в crm_state.db (таблица chat_messages) для чат-UI:

    python3 scripts/chat_projection.py --update     # инкрементально: новые файлы
    python3 scripts/chat_projection.py --rebuild    # с нуля
    python3 scripts/chat_projection.py --client "Мягкая кровля"   # посмотреть ленту

Одна строка ленты = одно сообщение: ts / direction / channel / author /
client / contact / chat_id / text / file. Этап «Чат как основа CRM» —
60_Reference/Chat_CRM_Architecture.md.
"""
import os
import re
import sys
import sqlite3
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
INBOX = BASE / "20_Inbox"
OUTBOX = BASE / "20_Outbox"
JOURNAL = BASE / "company" / "journal"   # вердикты ролей «Команды Автомата»
DB = BASE / "crm_state.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS chat_messages (
    id        TEXT PRIMARY KEY,   -- имя файла (уникальный ключ)
    ts        TEXT,               -- время сообщения (сортировка ленты)
    direction TEXT,               -- incoming | outgoing
    channel   TEXT,               -- telegram | email | webchat
    author    TEXT,               -- клиентский контакт | evgeny | jarvis
    client    TEXT,
    contact   TEXT,
    chat_id   TEXT,
    text      TEXT,
    file      TEXT
);
CREATE INDEX IF NOT EXISTS idx_chat_ts ON chat_messages(ts);
CREATE INDEX IF NOT EXISTS idx_chat_client ON chat_messages(client);
"""


def parse_frontmatter_text(text):
    m = re.match(r"^\s*---\n(.*?)\n---", text, re.DOTALL)
    meta = {}
    if m:
        try:
            import yaml
            y = yaml.safe_load(m.group(1))
            if isinstance(y, dict):
                meta = y
        except Exception:
            for line in m.group(1).splitlines():
                km = re.match(r"^([\w]+)\s*:\s*(.*)$", line)
                if km:
                    v = km.group(2).strip().strip('"').strip("'")
                    meta[km.group(1)] = v
    body = text[m.end():] if m else text
    # текст без заголовка и пустых строк
    lines = [l for l in body.splitlines() if l.strip() and not l.startswith("#")]
    text = "\n".join(lines).strip()
    # у email-файлов: отрезать мета-блок (**Subject**/**Date**/**Вложения:**...)
    if text.startswith("**Subject**") or text.startswith("**Тема"):
        kept, in_meta = [], True
        for l in lines:
            if in_meta and (l.startswith("**") or l.startswith("- ") or not l.strip()):
                if not l.strip() and kept:
                    in_meta = False
                continue
            in_meta = False
            kept.append(l)
        text = "\n".join(kept).strip()
    # чистка артефактов старых форматов: цитаты-обвязки, разделители, подписи
    cleaned = []
    skip_block = False
    for l in text.splitlines():
        ls = l.strip()
        if ls.startswith("> **Источник:**") or ls.startswith("[➡️"):
            skip_block = True
            continue
        if skip_block:
            if ls.startswith(">"):
                continue
            skip_block = False
        if ls in ("---", "--", "***"):
            continue
        if ls.startswith("Отправлено из Mail") or ls.startswith("-- "):
            continue
        cleaned.append(l)
    text = "\n".join(cleaned).strip()
    # HTML-сырец (mail.ru подписи/облако) → чистый текст
    if "<html" in text.lower() or "<body" in text.lower() or "<div" in text.lower():
        try:
            from bs4 import BeautifulSoup
            text = BeautifulSoup(text, "html.parser").get_text("\n", strip=True)
            lines2 = [l for l in text.splitlines()
                      if l.strip() and not l.strip().startswith("--")
                      and "Отправлено из" not in l]
            text = "\n".join(lines2).strip()
        except Exception:
            pass
    # пустой текст при вложении → имя вложения
    if (not text or text == "(вложение/медиа)") and meta.get("attachments"):
        atts = meta["attachments"]
        atts = atts if isinstance(atts, list) else [atts]
        text = "📎 " + os.path.basename(str(atts[0]))
    return meta, text[:2000]


def strip_wiki(v):
    return str(v or "").replace("[[", "").replace("]]", "").strip()


def project_file(path: Path):
    meta, body = parse_frontmatter_text(path.read_text(encoding="utf-8"))
    fname = path.name
    outgoing = fname.startswith("out_")
    if meta.get("analysis"):
        direction = "event"
    else:
        direction = "outgoing" if outgoing else "incoming"
    channel = str(meta.get("channel") or meta.get("source") or "").lower()
    if "email" in channel:
        channel = "email"
    elif any(k in channel for k in ("telegram", "группа", "личные")):
        channel = "telegram"
    elif "webchat" in channel:
        channel = "webchat"
    elif channel == "max" or "max" in channel:
        channel = "max"
    else:
        channel = channel or "unknown"
    client = strip_wiki(meta.get("client"))
    contact = str(meta.get("sender") or meta.get("sender_name") or meta.get("contact") or "").strip()
    if direction == "event":
        author = "jarvis"
        contact = ""
    elif outgoing:
        author = str(meta.get("author") or "evgeny")
        contact = meta.get("to") or ""
    else:
        author = contact or client or "client"
    ts = str(meta.get("date") or meta.get("created") or "")
    if len(ts) == 10:
        # время — из имени файла (tg-файлы хранят только дату в frontmatter)
        mt = re.search(r"(\d{4}-\d{2}-\d{2})_(\d{2})-(\d{2})", fname)
        ts = f"{ts} {mt.group(2)}:{mt.group(3)}:00" if mt else ts + " 00:00:00"
    if not re.match(r"\d{4}-\d{2}-\d{2}", ts):
        m2 = re.match(r"(\d{4}-\d{2}-\d{2})_(\d{2})-(\d{2})", fname)
        ts = (m2.group(1) + f" {m2.group(2)}:{m2.group(3)}:00") if m2 else "1970-01-01 00:00:00"
    return (fname, ts, direction, channel, author, client, contact,
            str(meta.get("chat_id") or meta.get("from") or ""), body or "(вложение/медиа)",
            str(path.relative_to(BASE)))


def project_journal_file(path):
    """Вердикт роли (company/journal) → строка ленты канала team.
    Журнал дописывается (ответы владельца), поэтому перечитывается всегда."""
    text = path.read_text(encoding="utf-8")
    meta, body = parse_frontmatter_text(text)
    role = str(meta.get("role") or path.stem.split("_")[-1] or "team")
    date = str(meta.get("date") or path.stem[:10] or "1970-01-01")
    ts = f"{date} 09:00:00"
    title = str(meta.get("title") or path.stem)
    body_clean = re.sub(r"\n{3,}", "\n\n", body).strip()
    text_out = f"{title}\n\n{body_clean}"
    return (path.name, ts, "outgoing", "team", role, "Команда Автомата", "",
            "team", text_out[:4000], str(path.relative_to(BASE)))


def update(rebuild=False):
    conn = sqlite3.connect(DB)
    conn.executescript(SCHEMA)
    if rebuild:
        conn.execute("DELETE FROM chat_messages")
        conn.commit()
    have = {r[0] for r in conn.execute("SELECT id FROM chat_messages")}
    n = 0
    for folder in (INBOX, OUTBOX, JOURNAL):
        if not folder.exists():
            continue
        for f in sorted(folder.glob("*.md")):
            if f.name == "README.md":
                continue
            if folder is not JOURNAL and f.name in have:
                continue
            try:
                row = (project_journal_file(f) if folder is JOURNAL
                       else project_file(f))
                conn.execute("INSERT OR REPLACE INTO chat_messages VALUES (?,?,?,?,?,?,?,?,?,?)", row)
                if f.name not in have:
                    n += 1
            except Exception as e:
                print(f"⚠️ {f.name}: {e}")
    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0]
    conn.close()
    print(f"✅ проекция: +{n} новых, всего {total} сообщений")


def show(client=None, limit=30):
    conn = sqlite3.connect(DB)
    q = "SELECT ts, direction, channel, author, client, substr(text,1,80) FROM chat_messages"
    args = ()
    if client:
        q += " WHERE client LIKE ?"
        args = (f"%{client}%",)
    q += " ORDER BY ts DESC LIMIT ?"
    args = args + (limit,)
    for r in conn.execute(q, args):
        mark = "→" if r[1] == "outgoing" else "←"
        print(f"{r[0][:16]} {mark} [{r[2]:8}] {r[3][:20]:20} | {r[4][:14]:14} | {r[5]}")
    conn.close()


if __name__ == "__main__":
    if "--rebuild" in sys.argv:
        update(rebuild=True)
    elif "--client" in sys.argv:
        show(sys.argv[sys.argv.index("--client") + 1])
    elif "--show" in sys.argv:
        show()
    else:
        update()
