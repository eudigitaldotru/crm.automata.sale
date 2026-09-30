"""
chat_export_profile.py — реестр участников из HTML-экспортов Telegram Desktop.

Разбирает файлы messages*.html (экспорт «Export chat history» → HTML) из
25_Chats/<Клиент>/raw/ и строит по каждому участнику:
  имя, число сообщений, период активности, средняя длина, доля медиа,
  примеры сообщений (первое/последнее).

Свои сообщения (без from_name) относятся к владельцу («Я»).

Запуск (системный python3 с bs4; bs4 в venv проекта нет):
    python3 scripts/chat_export_profile.py "25_Chats/Мягкая кровля/raw"

Вывод: сводная таблица в stdout + participants.json рядом с raw/ (для
последующей генерации карточек людей и профилей).
"""
import os
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from bs4 import BeautifulSoup

OWNER = os.getenv("CRM_OWNER_NAME", "Owner")


def clean_name(raw: str) -> str:
    # «Имя @username» → «Имя» + username отдельно; убираем «via @bot»
    username = ""
    m = re.search(r"@([A-Za-z0-9_]{4,})", raw or "")
    if m:
        username = m.group(1)
    name = re.sub(r"@\w+", "", raw or "").strip()
    return name or raw.strip(), username


def parse_file(path: Path):
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    chat_title = ""
    hdr = soup.find("div", class_="page_header")
    if hdr:
        chat_title = hdr.get_text(" ", strip=True)
    out = []
    for msg in soup.find_all("div", class_="message"):
        #joined/jservice-сообщения пропускаем (class contains "joined")
        classes = msg.get("class") or []
        if "joined" in classes or "service" in classes:
            continue
        fn = msg.find("div", class_="from_name")
        if fn:
            name, username = clean_name(fn.get_text(" ", strip=True))
        else:
            name, username = OWNER, ""
        dt = msg.find("div", class_="date")
        date = (dt.get("title") or "")[:16] if dt else ""
        # dd.mm.yyyy → yyyymmdd для корректного сравнения периодов
        date_sort = ""
        if date:
            parts = date.split(".")
            if len(parts) >= 3:
                date_sort = f"{parts[2][:4]}-{parts[1]}-{parts[0]}{date[10:]}"
        body = msg.find("div", class_="text")
        text = body.get_text(" ", strip=True) if body else ""
        # медиа: вложения без текста
        media = bool(msg.find("div", class_="media_wrap")) or (
            not text and bool(msg.find("img")))
        out.append({"from": name, "username": username, "date": date,
                    "date_sort": date_sort, "text": text, "media": media})
    return chat_title, out


def main():
    raw_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "25_Chats/raw")
    files = sorted(raw_dir.glob("*.html"))
    if not files:
        print(f"❌ HTML-файлы не найдены в {raw_dir}")
        sys.exit(1)

    stats = defaultdict(lambda: {"msgs": 0, "media": 0, "chars": 0,
                                 "first": None, "last": None,
                                 "first_text": "", "last_text": "",
                                 "username": ""})
    per_chat = defaultdict(lambda: defaultdict(int))  # чат → имя → n
    total = 0
    dates_all = []

    for f in files:
        title, msgs = parse_file(f)
        for m in msgs:
            total += 1
            s = stats[m["from"]]
            s["msgs"] += 1
            s["media"] += 1 if m["media"] else 0
            s["chars"] += len(m["text"])
            if m["username"]:
                s["username"] = m["username"]
            d = m.get("date_sort") or ""
            if d:
                dates_all.append(d)
                if s["first"] is None or d < s["first"]:
                    s["first"] = d
                    s["first_text"] = m["text"][:160]
                if s["last"] is None or d > s["last"]:
                    s["last"] = d
                    s["last_text"] = m["text"][:160]
            per_chat[title][m["from"]] += 1

    period = (min(dates_all)[:10], max(dates_all)[:10]) if dates_all else ("?", "?")
    print(f"📦 Разобрано: {len(files)} файл(ов), {total} сообщений, "
          f"период {period[0]} → {period[1]}")
    for title, people in per_chat.items():
        print(f"\nЧат: {title} ({sum(people.values())} сообщ., "
              f"{len(people)} участников писали)")

    print(f"\n{'Участник':34} {'сообщ.':>6} {'медиа':>5} {'ср.длина':>8}  "
          f"{'активность':23} username")
    print("-" * 100)
    for name, s in sorted(stats.items(), key=lambda kv: -kv[1]["msgs"]):
        avg = s["chars"] // max(1, s["msgs"] - s["media"])
        act = f"{(s['first'] or '?')[:10]} → {(s['last'] or '?')[:10]}"
        print(f"{name[:34]:34} {s['msgs']:>6} {s['media']:>5} {avg:>8}  "
              f"{act:23} @{s['username']}" if s["username"] else
              f"{name[:34]:34} {s['msgs']:>6} {s['media']:>5} {avg:>8}  {act:23}")

    out_file = raw_dir.parent / "participants.json"
    out_file.write_text(json.dumps(
        {k: v for k, v in stats.items()}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(f"\n💾 {out_file}")


if __name__ == "__main__":
    main()
