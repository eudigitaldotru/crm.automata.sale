"""
chat_history_import.py — импорт полной истории переписки в единую ленту.

Парсит HTML-экспорты Telegram Desktop из 25_Chats/<Клиент>/raw/*.html
(эталонные даты Telegram) и добавляет сообщения в crm_state.db.chat_messages
с id вида hist-<файл>-<msg>. Живые сообщения (20_Inbox/20_Outbox) остаются
как есть; дедуп — по (client, автор, дата±2мин, текст).

Запуск: python3 scripts/chat_history_import.py [--dry-run]
После — лента чата показывает ВСЮ историю клиента (годы), а не только
то, что поймал живой слушатель.
"""
import re
import sqlite3
import sys
from pathlib import Path

from bs4 import BeautifulSoup

BASE = Path(__file__).resolve().parent.parent
RAW_ROOT = BASE / "25_Chats"
DB = BASE / "crm_state.db"


def parse_date(title):
    """'21.05.2025 16:01' → '2025-05-21 16:01:00' (UTC+4 → как есть)."""
    m = re.match(r"(\d{2})\.(\d{2})\.(\d{4}) (\d{2}):(\d{2})", title or "")
    if not m:
        return None
    d, mo, y, h, mi = m.groups()
    return f"{y}-{mo}-{d} {h}:{mi}:00"


def import_history(dry_run=False):
    conn = sqlite3.connect(DB)
    have_keys = set()
    for r in conn.execute("SELECT client, author, ts, substr(text,1,60) FROM chat_messages"):
        have_keys.add((r[0], r[1], r[2][:16], r[3]))
    n_files, n_msgs, n_skip = 0, 0, 0
    for client_dir in sorted(RAW_ROOT.glob("*/raw")):
        client = client_dir.parent.name
        for f in sorted(client_dir.glob("*.html")):
            n_files += 1
            soup = BeautifulSoup(f.read_text(encoding="utf-8"), "html.parser")
            for msg in soup.find_all("div", class_="message"):
                classes = msg.get("class") or []
                if "joined" in classes or "service" in classes:
                    continue
                body = msg.find("div", class_="text")
                text = body.get_text(" ", strip=True) if body else ""
                if not text:
                    continue
                fn = msg.find("div", class_="from_name")
                author = fn.get_text(" ", strip=True) if fn else os.getenv("CRM_OWNER_NAME", "Owner")
                if author == os.getenv("CRM_OWNER_NAME", "Owner"):
                    direction, author_kind = "outgoing", "evgeny"
                else:
                    direction, author_kind = "incoming", author
                dt = msg.find("div", class_="date")
                ts = parse_date(dt.get("title") if dt else None)
                if not ts:
                    continue
                key = (client, author_kind, ts[:16], text[:60])
                if key in have_keys:
                    n_skip += 1
                    continue
                have_keys.add(key)
                row_id = f"hist-{f.stem[:20]}-{msg.get('id', abs(hash(text)) % 10**8)}"
                if not dry_run:
                    conn.execute(
                        "INSERT OR IGNORE INTO chat_messages VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (row_id, ts, direction, "telegram", author_kind, client,
                         author if direction == "incoming" else "",
                         "", text[:2000], str(f.relative_to(BASE))))
                n_msgs += 1
    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0]
    conn.close()
    print(f"{'[DRY] ' if dry_run else ''}история: {n_files} файлов, +{n_msgs} сообщений "
          f"(дубли: {n_skip}), всего в ленте: {total}")


if __name__ == "__main__":
    import_history(dry_run="--dry-run" in sys.argv)
