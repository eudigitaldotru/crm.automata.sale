#!/usr/bin/env python3
"""send_email.py — отправка письма клиенту из любой сессии (SMTP, мультиящик).

Usage:
  python3 scripts/send_email.py --to "client@mail.ru" --subject "Ответ" --text-file msg.txt \
      [--reply-to "<message-id>"] [--mailbox hello] [--from-name "…"] [--attach f.pdf] [--check]

  текст можно передать через pipe:  cat msg.txt | python3 scripts/send_email.py --to … --subject …
  --check — проверить логин/пароль ящика БЕЗ отправки (для подключения нового ящика).

Ящики: scripts/mailboxes.json (пароли в .env: MAILBOX__<id>__PASS, фолбэк EMAIL_PASS).
Ответ фиксируется в 20_Outbox/out_email_*.md (единая лента) с привязкой клиента.
"""
import argparse
import datetime
import json
import os
import pathlib
import re
import smtplib
import sys
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

BASE_DIR = pathlib.Path(__file__).resolve().parent.parent
sys.path.append(str(pathlib.Path(__file__).resolve().parent))
from mail_utils import get_mailbox, smtp_allowlist, mailbox_password  # noqa: E402


def validate_input_path(path, what="файл", allow_tmp=False):
    rp = os.path.realpath(path)
    if not os.path.isfile(rp):
        sys.exit(f"{what} не найден: {path}")
    roots = [os.path.realpath(str(BASE_DIR) + "/.."), os.path.realpath(os.getcwd())]
    if allow_tmp:  # только для ЧТЕНИЯ текста письма (не вложения): черновики из /tmp
        roots += [os.path.realpath("/tmp"), os.path.realpath(os.path.expanduser("~"))]
    if not any(os.path.commonpath([r, rp]) == r for r in roots):
        scope = "vault/рабочая папка" + ("/tmp/home" if allow_tmp else "")
        sys.exit(f"{what} вне разрешённых каталогов ({scope}): {rp}")
    return rp


def resolve_client(to):
    """Клиент по адресу получателя (.contact_index.json → by_email) —
    для привязки исходящего письма к клиенту в ленте чата."""
    try:
        idx = json.loads((BASE_DIR / "scripts" / ".contact_index.json")
                         .read_text(encoding="utf-8"))
        hit = idx.get("by_email", {}).get(to.strip().lower())
        if hit:
            return hit.get("client") or ""
    except Exception:
        pass
    return ""


def outbox_record(now, to, subject, text, att_names, client="", mailbox_id=""):
    stamp = now.strftime("%Y-%m-%d_%H-%M")
    safe = re.sub(r"[^0-9A-Za-z._-]+", "_", to.split("@")[0])[:30] or "client"
    fname = f"out_email_{stamp}_{safe}.md"
    if pathlib.PurePath(fname).name != fname or fname.startswith("."):
        raise RuntimeError("недопустимое имя outbox-файла")
    out_dir = BASE_DIR / "20_Outbox"
    target = out_dir / fname
    if target.parent.resolve() != out_dir.resolve():
        raise RuntimeError("путь вне 20_Outbox")
    n = 1
    while target.exists():
        target = out_dir / fname.replace(".md", f"_{n}.md")
        n += 1
    # кавычки/бэкслэши в теме ломают YAML-фронтматтер — вычищаем
    subject_fm = subject.replace('"', "'").replace("\\", "/")
    fm_mailbox = f"mailbox: {mailbox_id}\n" if mailbox_id else ""
    target.write_text(f"""---
type: outgoing
channel: email
source: smtp
author: jarvis
{fm_mailbox}to: "{to}"
{f'client: "[[{client}]]"' if client else '# client: не найден в contact_index'}
subject: "{subject_fm}"
date: {now.strftime('%Y-%m-%d %H:%M:%S')}
attachments: {json.dumps(att_names, ensure_ascii=False)}
---
# OUT → EMAIL {to} (jarvis)

## Тема
{subject}

## Текст
{text}
""", encoding="utf-8")
    return target.name


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", help="адрес получателя")
    ap.add_argument("--subject", help="тема письма")
    ap.add_argument("--text", help="текст письма")
    ap.add_argument("--text-file", help="текст из файла (или передайте через stdin)")
    ap.add_argument("--stdin", action="store_true", help="взять текст из stdin (pipe)")
    ap.add_argument("--reply-to", default="", help="Message-ID письма, на которое отвечаем")
    ap.add_argument("--mailbox", default="", help="id ящика из scripts/mailboxes.json (по умолчанию default)")
    ap.add_argument("--from-name", default="Automata CRM assist · ИИ-ассистент Евгения")
    ap.add_argument("--attach", action="append", default=[])
    ap.add_argument("--check", action="store_true",
                    help="проверить подключение ящика (SMTP login) без отправки письма")
    args = ap.parse_args()

    mbox = get_mailbox(args.mailbox or None)
    if not mbox:
        sys.exit(f"ящик не найден ({args.mailbox or 'default'}): см. scripts/mailboxes.json")
    mbox_id = mbox["id"]
    host = mbox.get("smtp_host", "smtp.timeweb.ru")
    port = int(mbox.get("smtp_port", 465))
    if host not in smtp_allowlist():
        sys.exit(f"smtp-хост вне allowlist активных ящиков: {host}")
    user = mbox["email"]
    pwd = mailbox_password(mbox)
    if not pwd:
        sys.exit(f"пароль не найден: .env MAILBOX__{mbox_id}__PASS (или EMAIL_PASS)")

    if args.check:
        try:
            with smtplib.SMTP_SSL(host, port, timeout=20) as s:
                s.login(user, pwd)
            print(f"✅ [{mbox_id}] {user}: SMTP {host} логин OK")
            return
        except Exception as e:
            sys.exit(f"❌ [{mbox_id}] {user}: SMTP {host} — {e}")

    if not args.to:
        sys.exit("нужен --to (или --check для проверки ящика)")
    if args.text_file:
        args.text = open(validate_input_path(args.text_file, "текст", allow_tmp=True),
                         encoding="utf-8").read()
    elif args.stdin or (not args.text and not sys.stdin.isatty()):
        args.text = sys.stdin.read()
    text = (args.text or "").strip()
    if not text and not args.attach:
        sys.exit("пустое письмо")
    if not args.subject:
        sys.exit("нужен --subject")
    if not re.match(r"[^@\s]+@[^@\s]+\.[^@\s]+", args.to):
        sys.exit("некорректный адрес получателя")

    msg = EmailMessage()
    msg["From"] = f"{args.from_name} <{user}>"
    msg["To"] = args.to
    msg["Subject"] = args.subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=user.split("@")[1] if "@" in user else "localhost")
    if args.reply_to:
        msg["In-Reply-To"] = args.reply_to.strip()
        msg["References"] = args.reply_to.strip()
    msg.set_content(text)

    att_names = []
    for p in args.attach:
        rp = validate_input_path(p, "вложение")
        data = open(rp, "rb").read()
        ctype = "application/octet-stream"
        if rp.lower().endswith(".pdf"):
            ctype = "application/pdf"
        elif rp.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            ctype = "image/" + ("jpeg" if rp.lower().endswith((".jpg", ".jpeg")) else
                                "png" if rp.lower().endswith(".png") else "webp")
        msg.add_attachment(data, maintype=ctype.split("/")[0], subtype=ctype.split("/")[1],
                           filename=os.path.basename(rp))
        att_names.append(os.path.basename(rp))

    with smtplib.SMTP_SSL(host, port, timeout=30) as s:
        s.login(user, pwd)
        s.send_message(msg)

    now = datetime.datetime.now()
    client = resolve_client(args.to)
    fname = outbox_record(now, args.to, args.subject, text, att_names, client, mbox_id)
    print(f"✅ отправлено [{mbox_id}] {user} → {args.to} | тема: {args.subject[:60]}")
    print(f"📝 зафиксировано: {fname}"
          + (f" | клиент: {client}" if client else " | ⚠️ клиент не сопоставлен"))


if __name__ == "__main__":
    main()
