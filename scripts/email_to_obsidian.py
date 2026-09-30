
from sec_guard import guard_open
import os
import imaplib
import email
import email as email_lib
import json
import html as html_lib
from email.header import decode_header
import datetime
from datetime import timedelta
from dotenv import load_dotenv
import sys
import re

# Ensure we can import from utils
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from utils.client_loader import load_client_emails
from mail_utils import load_mailboxes

# --- FORCE DISABLE PROXY ---
for key in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY']:
    os.environ.pop(key, None)

load_dotenv()

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INBOX_DIR = os.path.join(BASE, "20_Inbox")
ATT_DIR = os.path.join(INBOX_DIR, "attachments")
CLIENTS_DIR = os.path.join(BASE, "10_Clients")
# State: per-mailbox {"mailboxes": {<id>: {last_check, seen}}} — дата последней
# проверки (IMAP SINCE) + seen Message-ID/дедуп-ключей, чтобы ловить письма,
# прочитанные владельцем с телефона ДО прогона (UNSEEN их скрывал)
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".email_state.json")


def load_state():
    try:
        with guard_open(STATE_FILE, encoding="utf-8") as f:
            st = json.load(f)
    except Exception:
        st = {}
    # миграция старого формата {last_check, seen} → под ящик .env (default/hello)
    if "mailboxes" not in st:
        legacy = {"last_check": st.get("last_check"), "seen": st.get("seen", [])}
        mbox_id = "hello" if any(m["id"] == "hello" for m in load_mailboxes()) else "default"
        st = {"mailboxes": {mbox_id: legacy}}
    return st


def save_state(st):
    for m in st.get("mailboxes", {}).values():
        m["seen"] = (m.get("seen") or [])[-500:]
    with guard_open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False)


def get_allowed_emails():
    """Returns a set of allowed emails from 10_Clients."""
    print(f"Scanning clients in: {CLIENTS_DIR}")
    client_map = load_client_emails(CLIENTS_DIR)
    print(f"Loaded {len(client_map)} client emails.")
    return set(client_map.keys()), client_map


def clean_filename(s):
    keepcharacters = (' ', '.', '_', '-')
    return "".join(c for c in s if c.isalnum() or c in keepcharacters).rstrip().replace(" ", "_")


def decode_mime_words(s):
    if not s:
        return ""
    return u''.join(
        word.decode(encoding or 'utf-8', errors='replace') if isinstance(word, bytes) else word
        for word, encoding in decode_header(s)
    )


def decode_payload_text(part):
    """Текст part с учётом charset письма (cp1251/koi8-r раньше давали кракозябры)."""
    payload = part.get_payload(decode=True)
    if not payload:
        return ""
    charset = (part.get_content_charset() or "utf-8").lower()
    if charset in ("default", "unknown-8bit", "x-unknown"):
        charset = "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except (LookupError, UnicodeDecodeError):
        for fallback in ("utf-8", "cp1251", "koi8-r", "latin-1"):
            try:
                return payload.decode(fallback)
            except UnicodeDecodeError:
                continue
    return payload.decode("utf-8", errors="ignore")


def html_to_text(html_text):
    """Грубый HTML → текст: письма без text/plain раньше сохранялись с пустым телом."""
    html_text = re.sub(r'(?is)<(style|script|head)[^>]*>.*?</\1>', ' ', html_text)
    html_text = re.sub(r'(?i)<br\s*/?>', '\n', html_text)
    html_text = re.sub(r'(?i)</(p|div|tr|li|h[1-6])>', '\n', html_text)
    html_text = re.sub(r'<[^>]+>', ' ', html_text)
    text = html_lib.unescape(html_text)
    text = re.sub(r'[ \t]+', ' ', text)
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def fetch_emails():
    mboxes = load_mailboxes(active_only=True, with_secret=True)
    if not mboxes:
        print("❌ Нет активных ящиков (scripts/mailboxes.json) и нет EMAIL_USER в .env")
        return

    allowed_emails, client_map = get_allowed_emails()
    state = load_state()

    for mbox in mboxes:
        try:
            _fetch_one_mailbox(mbox, allowed_emails, client_map, state)
        except Exception as e:
            print(f"❌ [{mbox['id']}] ящик не обработан: {e}")
    save_state(state)


def _fetch_one_mailbox(mbox, allowed_emails, client_map, state):
    mbox_id = mbox["id"]
    mstate = state.setdefault("mailboxes", {}).setdefault(
        mbox_id, {"last_check": None, "seen": []})
    seen_ids = set(mstate.get("seen", []))
    imap_host = mbox.get("imap_host", "imap.timeweb.ru")
    user = mbox["email"]
    pwd = mbox.get("password", "")

    print(f"\n=== 📬 Ящик [{mbox_id}] {user} ({imap_host}) ===")
    if not pwd:
        print(f"❌ [{mbox_id}] пароль не найден (.env: MAILBOX__{mbox_id}__PASS / EMAIL_PASS)")
        return

    try:
        mail = imaplib.IMAP4_SSL(imap_host)
        mail.login(user, pwd)
        mail.select("inbox")
    except Exception as e:
        print(f"❌ [{mbox_id}] Connection failed: {e}")
        return

    # SINCE-окно (fetch_days, по умолч. 7) вместо UNSEEN: письма, прочитанные
    # владельцем с телефона раньше прогона, тоже забираем; дедуп — по
    # Message-ID / дедуп-ключу (state)
    since = (datetime.date.today() - timedelta(days=int(mbox.get("fetch_days", 7)))).strftime("%d-%b-%Y")
    status, messages = mail.search(None, f'(SINCE "{since}")')
    email_ids = messages[0].split()
    print(f"[{mbox_id}] Found {len(email_ids)} emails since {since}.")

    for email_id in email_ids:
        try:
            res, msg_data = mail.fetch(email_id, "(RFC822)")
            for response_part in msg_data:
                if not isinstance(response_part, tuple):
                    continue
                msg = email.message_from_bytes(response_part[1])

                subject = decode_mime_words(msg["Subject"]) or "No Subject"
                msg_id = (msg.get("Message-ID") or "").strip()

                from_header = decode_mime_words(msg.get("From"))
                sender_email = email_lib.utils.parseaddr(from_header)[1].lower()

                # Дата — нужна и для дедупа писем без Message-ID
                date_tuple = email_lib.utils.parsedate_tz(msg["Date"])
                if date_tuple:
                    local_date = datetime.datetime.fromtimestamp(email_lib.utils.mktime_tz(date_tuple))
                else:
                    local_date = datetime.datetime.now()
                date_str = local_date.strftime("%Y-%m-%d %H:%M:%S")
                filename_date = local_date.strftime("%Y-%m-%d_%H-%M")

                # Дедуп: Message-ID, а без него — sender|subject|date
                dedup_key = msg_id or f"noid|{sender_email}|{subject}|{filename_date}"
                if dedup_key in seen_ids:
                    continue

                # FILTER: свои → как раньше; чужие не-bulk → инбокс с unmatched
                # (лид/спам решит 15-минутный разбор по тексту); bulk — мимо
                is_known = sender_email in allowed_emails
                if not is_known:
                    local_part = sender_email.split("@")[0].lower()
                    auto_sender = local_part in ("noreply", "no-reply", "donotreply",
                                                 "newsletter", "education", "news", "notify")
                    bulk = auto_sender or (msg.get("List-Unsubscribe")
                                           or msg.get("Precedence") == "bulk"
                                           or msg.get("Auto-Submitted") not in (None, "no"))
                    if bulk:
                        seen_ids.add(dedup_key)
                        continue

                if is_known:
                    print(f"  ✅ MATCH! Client: {client_map.get(sender_email)}")
                else:
                    print(f"  ❔ unmatched sender: {sender_email} → инбокс на разбор")

                # Extract Body + Attachments (вложения → 20_Inbox/attachments/)
                body = ""
                html_body = ""
                attachments = []
                for part in msg.walk():
                    fn = part.get_filename()
                    if fn:
                        fn_dec = decode_mime_words(fn)
                        payload = part.get_payload(decode=True)
                        if payload:
                            safe_fn = re.sub(r"[^\w\.\- ]", "_", fn_dec)[:80] or "attachment"
                            day_dir = os.path.join(
                                ATT_DIR,
                                local_date.strftime("%Y-%m-%d") + "_" +
                                re.sub(r"[^\w\-]", "_", sender_email.split("@")[0])[:20])
                            os.makedirs(day_dir, exist_ok=True)
                            out_path = os.path.join(day_dir, safe_fn)
                            b_, e_ = os.path.splitext(out_path)
                            n_ = 1
                            while os.path.exists(out_path):
                                out_path = f"{b_}_{n_}{e_}"
                                n_ += 1
                            with guard_open(out_path, "wb") as af:
                                af.write(payload)
                            attachments.append(os.path.relpath(out_path, BASE))
                    elif part.get_content_type() == "text/plain":
                        body += decode_payload_text(part)
                    elif part.get_content_type() == "text/html":
                        html_body += decode_payload_text(part)
                if not body.strip() and html_body:
                    body = html_to_text(html_body)

                # Create Markdown File
                safe_sender = clean_filename(sender_email)
                safe_subject = clean_filename(subject)[:50]
                # Вложенные кавычки в subject ломают YAML-фронтматер — вычищаем
                subject_fm = subject.replace('"', "'").replace("\\", "/")
                filename = f"{filename_date}_Email_{safe_sender}_{safe_subject}.md"
                filepath = os.path.join(INBOX_DIR, filename)

                att_yaml = ("attachments:\n" + "\n".join(f"  - {a}" for a in attachments)) if attachments else ""
                att_md = ("\n**Вложения:**\n" + "\n".join(f"- {a}" for a in attachments)) if attachments else ""
                md_content = f"""---
type: incoming
source: email
mailbox: {mbox_id}
sender: {sender_email}
{f'client: "[[{client_map.get(sender_email)}]]"' if is_known else "unmatched: true"}
date: {date_str}
subject: "{subject_fm}"
message_id: "{msg_id[:120]}"
{att_yaml}
---
# Email from {sender_email}

**Subject**: {subject}
**Date**: {date_str}
{att_md}

---

{body}
"""
                with guard_open(filepath, "w", encoding="utf-8") as f:
                    f.write(md_content)

                print(f"  💾 [{mbox_id}] Saved: {filename}" + (f" (+{len(attachments)} вложений)" if attachments else ""))
                seen_ids.add(dedup_key)

                try:
                    from hub_push import send_event
                    send_event(
                        "new_email",
                        f"Почта: {subject[:80]}",
                        dedup_key=f"mail-{sender_email}-{filename_date}",
                        payload={"sender": sender_email,
                                 "client": client_map.get(sender_email),
                                 "subject": subject[:200]},
                        push={"title": f"✉️ {client_map.get(sender_email) or sender_email}",
                              "body": subject[:80], "channel": "messages"},
                    )
                except Exception:
                    pass

        except Exception as e:
            print(f"❌ [{mbox_id}] Error processing email {email_id}: {e}")

    mstate["seen"] = list(seen_ids)
    mstate["last_check"] = datetime.date.today().isoformat()

    try:
        mail.close()
        mail.logout()
    except Exception:
        pass


if __name__ == "__main__":
    fetch_emails()
