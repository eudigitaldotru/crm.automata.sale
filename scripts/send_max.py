#!/usr/bin/env python3
"""send_max.py — отправка сообщения (и вложений) от бота в MAX-чат из любой сессии/проекта.

Usage:
  python3 scripts/send_max.py <chat_id> "текст" [--attach file.pdf] [--author jarvis]
  python3 scripts/send_max.py --by-title "Мир Панелей SEO" --text-file msg.txt [--attach o.pdf]
Ответ фиксируется в 20_Outbox/out_max_*.md (аналогично TG-отправке через gateway).

Автор всегда бот (= Джарвис, если --author jarvis; подпись в текст добавляет вызывающий).
"""
import argparse
import datetime
import ipaddress
import json
import os
import pathlib
import re
import socket
import sys
import urllib.request
import urllib.parse
import uuid
from urllib.parse import urlparse

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = "https://botapi.max.ru"
ALLOWED_HOSTS = {"botapi.max.ru"}  # upload-хост добавляется динамически после IP-проверки


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):
        return None


def _guard_url(url):
    """SSRF-защита: только https, хост из allowlist, IP не приватный/loopback/link-local."""
    p = urlparse(url)
    if p.scheme != "https":
        raise RuntimeError(f"запрещена схема URL: {p.scheme}")
    host = p.hostname or ""
    if host not in ALLOWED_HOSTS:
        raise RuntimeError(f"хост вне allowlist: {host}")
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise RuntimeError(f"DNS не разрешил {host}: {e}")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise RuntimeError(f"хост {host} резолвится в запрещённый IP {ip}")


def http_json(method, url, headers=None, data=None, timeout=40, allow_host=None):
    if allow_host and allow_host not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.add(allow_host)
    _guard_url(url)
    opener = urllib.request.build_opener(NoRedirect)
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with opener.open(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode()[:400]
        except Exception:
            pass
        raise RuntimeError(f"HTTP {e.code} на {method} {url}: {detail}") from e


def validate_input_path(path, what="файл"):
    """Пути из аргументов: обычный файл строго внутри разрешённых корней (vault или cwd)."""
    rp = os.path.realpath(path)
    if not os.path.isfile(rp):
        sys.exit(f"{what} не найден: {path}")
    roots = [os.path.realpath(BASE_DIR + "/.."), os.path.realpath(os.getcwd())]
    if not any(os.path.commonpath([r, rp]) == r for r in roots):
        sys.exit(f"{what} вне разрешённых каталогов (vault/рабочая папка): {rp}")
    return rp


def resolve_by_title(title):
    """Ищет max_chats.id по title во всех карточках 10_Clients/*.md."""
    import glob
    rx = re.compile(r"id:\s*\"(-?\d+)\"\s*\n\s*title:\s*\"([^\"]+)\"")
    for f in glob.glob(os.path.join(BASE_DIR, "10_Clients", "**", "*.md"), recursive=True):
        try:
            txt = open(f, encoding="utf-8").read()
        except OSError:
            continue
        if "max_chats" not in txt:
            continue
        for m in rx.finditer(txt):
            if title.lower() in m.group(2).lower():
                return m.group(1), m.group(2), os.path.basename(f)
    return None


def upload_file(token, path):
    """MAX Bot API: POST /uploads?type=file → внешний url → multipart POST → token."""
    path = validate_input_path(path, "вложение")
    up = http_json("POST", f"{API}/uploads?type=file", headers={"Authorization": token})
    url = up["url"]
    host = urlparse(url).hostname
    fn = os.path.basename(path)
    boundary = uuid.uuid4().hex
    with open(path, "rb") as fh:
        blob = fh.read()
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"data\"; "
            f"filename=\"{fn}\"\r\nContent-Type: application/octet-stream\r\n\r\n").encode() \
        + blob + f"\r\n--{boundary}--\r\n".encode()
    resp = http_json("POST", url, allow_host=host,
                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
                     data=body, timeout=180)
    tokn = resp.get("token") or resp.get("file", {}).get("token")
    if not tokn:
        raise RuntimeError(f"upload не вернул token: {json.dumps(resp, ensure_ascii=False)[:300]}")
    return tokn


def write_outbox_record(chat_id, now, content):
    """Фиксация в 20_Outbox: имя только из даты и верифицированного числового chat_id."""
    m = re.fullmatch(r"-?\d+", str(chat_id))
    safe_id = m.group(0).replace("-", "g") if m else "chat"
    fname = now.strftime("out_max_%Y-%m-%d_%H-%M_") + safe_id + ".md"
    if pathlib.Path(fname).name != fname or fname.startswith("."):
        raise RuntimeError("недопустимое имя outbox-файла")
    out_dir = pathlib.Path(BASE_DIR) / "20_Outbox"
    target = out_dir / fname
    if target.parent.resolve() != out_dir.resolve():
        raise RuntimeError("путь outbox вышел за пределы 20_Outbox")
    target.write_text(content, encoding="utf-8")
    return fname


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("chat_id", nargs="?", help="chat_id группы (или --by-title)")
    ap.add_argument("text", nargs="?", help="текст сообщения")
    ap.add_argument("--by-title", help="найти chat_id по title из max_chats карточек")
    ap.add_argument("--text-file", help="взять текст из файла")
    ap.add_argument("--attach", action="append", default=[], help="файл-вложение (можно несколько)")
    ap.add_argument("--author", default="jarvis", choices=["jarvis", "evgeny"])
    args = ap.parse_args()

    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, ".env"))
    token = os.getenv("MAX_BOT_TOKEN")
    if not token:
        sys.exit("MAX_BOT_TOKEN не найден в AUTOMATA-CRM/.env")

    client_file = None
    chat_title = None
    if args.by_title:
        found = resolve_by_title(args.by_title)
        if not found:
            sys.exit(f"Группа «{args.by_title}» не найдена в max_chats карточек 10_Clients")
        args.chat_id, chat_title, client_file = found
    if not args.chat_id:
        sys.exit("нужен chat_id или --by-title")
    if args.text_file:
        args.text = open(validate_input_path(args.text_file, "текстовый файл"),
                         encoding="utf-8").read()
    text = (args.text or "").strip()
    if not text and not args.attach:
        sys.exit("пустое сообщение")

    attachments = []
    for p in args.attach:
        attachments.append({"type": "file", "payload": {"token": upload_file(token, p)}})
        print(f"📎 загружено: {os.path.basename(p)}")

    # Рабочий формат MAX Bot API (проверен боем): chat_id в query,
    # text/attachments — JSON body. Полный query падает: 414/502 на длинных текстах.
    payload = {"text": text or " "}
    if attachments:
        payload["attachments"] = attachments
    out = http_json("POST", f"{API}/messages?chat_id={args.chat_id}",
                    headers={"Authorization": token, "Content-Type": "application/json"},
                    data=json.dumps(payload, ensure_ascii=False).encode())
    mid = out.get("message", {}).get("body", {}).get("mid", "")
    print(f"✅ отправлено: chat={args.chat_id} mid={mid}")

    # фиксация в 20_Outbox (единая лента)
    now = datetime.datetime.now()
    client = f"[[{os.path.basename(client_file)[:-3]}]]" if client_file else '""'
    record = f"""---
type: outgoing
channel: max
source: max-bot-api
author: {args.author}
chat_id: "{args.chat_id}"
client: {client}
date: {now:%Y-%m-%d %H:%M:%S}
mid: {mid}
attachments: {json.dumps([os.path.basename(a) for a in args.attach], ensure_ascii=False)}
---
# OUT → MAX {chat_title or args.chat_id} ({args.author})

{text}
"""
    fname = write_outbox_record(args.chat_id, now, record)
    print(f"📝 зафиксировано: {fname}")


if __name__ == "__main__":
    main()
