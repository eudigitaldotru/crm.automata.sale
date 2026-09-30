
from sec_guard import guard_open
import json
import os
import re
import smtplib
from email.message import EmailMessage
from email.utils import formatdate
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
dotenv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
load_dotenv(dotenv_path)

SMTP_SERVER = os.getenv("EMAIL_SMTP_HOST", "smtp.timeweb.ru")
SMTP_PORT = int(os.getenv("EMAIL_SMTP_PORT", 465))
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")

MAILBOXES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mailboxes.json")


def load_mailboxes(active_only=True, with_secret=False):
    """Ящики из scripts/mailboxes.json (пароли — только при with_secret=True).

    Фолбэк: файла нет/пуст → одиночный .env-ящик (EMAIL_USER/EMAIL_PASS) —
    обратная совместимость до появления конфига.
    """
    mboxes = []
    try:
        with guard_open(MAILBOXES_FILE, encoding="utf-8") as f:
            raw = json.load(f)
        mboxes = list(raw.get("mailboxes", []))
    except Exception:
        pass
    if not mboxes and os.getenv("EMAIL_USER"):
        mboxes = [{
            "id": "default",
            "email": os.getenv("EMAIL_USER"),
            "name": os.getenv("EMAIL_USER"),
            "imap_host": os.getenv("EMAIL_IMAP_HOST", "imap.timeweb.ru"),
            "smtp_host": os.getenv("EMAIL_SMTP_HOST", "smtp.timeweb.ru"),
            "smtp_port": int(os.getenv("EMAIL_SMTP_PORT", "465")),
            "active": True, "default": True, "fetch_days": 7,
        }]
    out = []
    for m in mboxes:
        mid = str(m.get("id", "")).strip()
        if not re.fullmatch(r"[A-Za-z0-9_\-]+", mid) or "@" not in str(m.get("email", "")):
            continue  # битые записи пропускаем — id попадает в имя env-переменной
        if active_only and not m.get("active", True):
            continue
        if with_secret:
            m = dict(m, password=mailbox_password(m))
        out.append(m)
    return out


def get_mailbox(mailbox_id=None):
    """Ящик по id; без id — default (или первый активный). None, если не найден."""
    mboxes = load_mailboxes(active_only=False)
    if not mboxes:
        return None
    if mailbox_id:
        for m in mboxes:
            if m["id"] == mailbox_id and m.get("active", True):
                return m
        return None
    for m in mboxes:
        if m.get("default") and m.get("active", True):
            return m
    active = [m for m in mboxes if m.get("active", True)]
    return active[0] if active else None


def mailbox_password(mbox):
    """Пароль ящика: .env MAILBOX__<id>__PASS, фолбэк EMAIL_PASS."""
    return (os.getenv(f"MAILBOX__{mbox['id']}__PASS")
            or os.getenv("EMAIL_PASS") or "")


def smtp_allowlist():
    """Разрешённые SMTP-хосты = хосты всех активных ящиков."""
    return {m.get("smtp_host", "smtp.timeweb.ru") for m in load_mailboxes()}


def log_outgoing_email(to_email, subject, body_text, author="evgeny"):
    """Исходящее письмо → 20_Outbox/ (единая история ленты чата CRM)."""
    try:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        out_dir = os.path.join(base, "20_Outbox")
        os.makedirs(out_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
        safe = re.sub(r"[^\w\-.]", "_", to_email)[:40]
        fname = f"out_email_{ts}_{safe}.md"
        path = os.path.join(out_dir, fname)
        n = 1
        while os.path.exists(path):
            path = os.path.join(out_dir, fname.replace(".md", f"_{n}.md"))
            n += 1
        with guard_open(path, "w", encoding="utf-8") as f:
            f.write(f"""---
type: outgoing
channel: email
author: {author}
to: "{to_email}"
date: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
subject: "{str(subject).replace('"', "'")}"
---
# OUT → ✉️ {to_email} ({author})

**Subject**: {subject}

{body_text}
""")
    except Exception:
        pass


def send_mail(to_email, subject, body_text, attachment_path=None, author="evgeny"):
    if not EMAIL_USER or not EMAIL_PASS:
        print("❌ Error: EMAIL_USER or EMAIL_PASS not found in .env file.")
        return False
        
    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = f"Automata CRM <{EMAIL_USER}>"
    msg['To'] = to_email
    msg['Date'] = formatdate(localtime=True)
    
    msg.set_content(body_text)
    
    if attachment_path and os.path.exists(attachment_path):
        filename = os.path.basename(attachment_path)
        try:
            with guard_open(attachment_path, 'rb') as f:
                data = f.read()
            # Basic type detection based on extension
            if filename.endswith('.pdf'):
                maintype, subtype = 'application', 'pdf'
            else:
                maintype, subtype = 'application', 'octet-stream'
                
            msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)
        except Exception as e:
            print(f"❌ Failed to attach {attachment_path}: {e}")
            return False

    try:
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
            server.login(EMAIL_USER, EMAIL_PASS)
            server.send_message(msg)
        log_outgoing_email(to_email, subject, body_text, author=author)
        return True
    except Exception as e:
        print(f"❌ Failed to send email: {e}")
        return False
