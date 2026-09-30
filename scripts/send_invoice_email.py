
from sec_guard import guard_open, guard_requests_post
import os
import sys
import yaml
import smtplib
import re
import base64
import requests
from email.message import EmailMessage
from email.utils import formatdate
from dotenv import load_dotenv

# Load environment variables
dotenv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
load_dotenv(dotenv_path)

SMTP_SERVER = "smtp.timeweb.ru"
SMTP_PORT = 465  # SSL port for Timeweb
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")

def parse_frontmatter(file_path):
    """Parses YAML frontmatter from a Markdown file."""
    try:
        with guard_open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        match = re.search(r'^\s*---\n(.*?)\n---', content, re.DOTALL)
        if match:
            return yaml.safe_load(match.group(1)), content
    except Exception as e:
        print(f"Error parsing file: {e}")
    return {}, ""

def find_client_file(client_link):
    """Resolves [[Client Name]] to a file path."""
    client_name = client_link.replace('[[', '').replace(']]', '')
    base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    client_path = os.path.join(base_path, "10_Clients", f"{client_name}.md")
    
    if os.path.exists(client_path):
        return client_path
    
    clients_dir = os.path.join(base_path, "10_Clients")
    if os.path.exists(clients_dir):
        for fname in os.listdir(clients_dir):
            if client_name in fname:
                return os.path.join(clients_dir, fname)
                
    return None

def extract_pdf_path(inv_meta, content, is_act=False):
    """Extracts the local PDF path. Prioritizes frontmatter properties."""
    pdf_filename = None
    if is_act:
        pdf_filename = inv_meta.get("act_pdf")
    else:
        pdf_filename = inv_meta.get("invoice_pdf")
        
    if pdf_filename:
        vault_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        pdf_path = os.path.join(vault_dir, "60_Documents", pdf_filename)
        if os.path.exists(pdf_path):
            return pdf_path

    # Fallback to visual markdown block parsing
    # Look for: [PDF](file:///path/to/file.pdf)
    if is_act:
        match = re.search(r'- \[x\] Акт выполненных работ \(\[PDF\]\((file://)?(.*?\.pdf)\)\)', content)
    else:
        match = re.search(r'- \[x\] Счёт \(PDF\) \(\[PDF\]\((file://)?(.*?\.pdf)\)\)', content)
        
    if match:
        path = match.group(2)
        # If relative, make absolute based on AUTOMATA-CRM root
        if not path.startswith('/'):
            base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            path = os.path.join(base_path, "60_Documents", os.path.basename(path))
        return path
    return None

def get_product_description(product_name):
    """Reads description from a product file in 70_Products/."""
    base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    product_path = os.path.join(base_path, "70_Products", f"{product_name}.md")
    if os.path.exists(product_path):
        try:
            with guard_open(product_path, 'r', encoding='utf-8') as f:
                content = f.read()
            match = re.search(r'^\s*---\n(.*?)\n---', content, re.DOTALL)
            if match:
                meta = yaml.safe_load(match.group(1))
                return meta.get('description')
        except:
            pass
    return None


def update_invoice_metadata(file_path, message_id=None, status="sent", body_text=None):
    """Updates the invoice metadata after successful sending."""
    try:
        with guard_open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        match = re.search(r'^(\s*---\n)(.*?)(\n---)', content, re.DOTALL)
        if not match:
            print("⚠️ Could not find frontmatter to update.")
            return

        header, fm_text, footer = match.groups()
        meta = yaml.safe_load(fm_text) or {}

        # 1. Update tags
        tags = meta.get('tags', [])
        if isinstance(tags, str):
            tags = [tags]
        if 'sent' not in tags:
            tags.append('sent')
        meta['tags'] = tags

        # 2. Increment sent_count
        count = int(meta.get('sent_count', 0))
        meta['sent_count'] = count + 1

        # 3. Email tracking metadata
        if message_id:
            meta['email_message_id'] = message_id
            meta['email_status'] = status
            
        if body_text:
            meta['email_body_preview'] = body_text

        # 4. Serialize back (using block style for tags to avoid flow style issues)
        # Note: We use safe_dump but need to be careful about not losing other data
        new_fm = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False, default_flow_style=False)
        
        updated_content = header + new_fm.strip() + footer + content[match.end():]
        
        with guard_open(file_path, 'w', encoding='utf-8') as f:
            f.write(updated_content)
        print(f"📝 Updated metadata: sent_count={meta['sent_count']}, tags=sent, email_status={status}")
    except Exception as e:
        print(f"⚠️ Failed to update metadata: {e}")

def send_email_smtp(to_email, subject, body_text, attachment_path=None, invoice_md_path=None):
    if not EMAIL_USER or not EMAIL_PASS:
        print("❌ Error: EMAIL_USER or EMAIL_PASS not found in .env file.")
        return False
        
    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = EMAIL_USER
    msg['To'] = to_email
    msg['Date'] = formatdate(localtime=True)
    
    msg.set_content(body_text)
    
    if attachment_path and os.path.exists(attachment_path):
        filename = os.path.basename(attachment_path)
        try:
            with guard_open(attachment_path, 'rb') as f:
                pdf_data = f.read()
            msg.add_attachment(pdf_data, maintype='application', subtype='pdf', filename=filename)
            print(f"📎 Attached: {filename}")
        except Exception as e:
            print(f"❌ Failed to attach {attachment_path}: {e}")
            return False
    elif attachment_path:
        print(f"❌ Attachment not found at: {attachment_path}")
        return False

    try:
        print(f"Connecting to {SMTP_SERVER}...")
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
            server.login(EMAIL_USER, EMAIL_PASS)
            server.send_message(msg)
            
        print(f"✅ Email sent successfully to {to_email}")
        
        if invoice_md_path:
            update_invoice_metadata(invoice_md_path, body_text=body_text)
        
        return True
    except Exception as e:
        print(f"❌ Failed to send email via SMTP: {e}")
        return False

def send_email_resend(to_email, subject, body_text, attachment_path=None, invoice_md_path=None):
    api_key = os.getenv("RESEND_API_KEY")
    if not api_key:
        print("❌ Error: RESEND_API_KEY not found in .env file.")
        return False
        
    url = "https://api.resend.com/emails"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    html_body = body_text.replace('\n', '<br>')
    
    payload = {
        "from": f"Automata CRM <{EMAIL_USER}>",
        "to": [to_email],
        "subject": subject,
        "html": html_body,
        "text": body_text
    }
    
    if attachment_path and os.path.exists(attachment_path):
        filename = os.path.basename(attachment_path)
        try:
            with guard_open(attachment_path, 'rb') as f:
                pdf_data = f.read()
            b64_content = base64.b64encode(pdf_data).decode('utf-8')
            payload["attachments"] = [
                {
                    "filename": filename,
                    "content": b64_content
                }
            ]
            print(f"📎 Attached: {filename}")
        except Exception as e:
            print(f"❌ Failed to attach {attachment_path}: {e}")
            return False
            
    try:
        print("Connecting to Resend API...")
        response = guard_requests_post(url, headers=headers, json=payload)
        
        if response.status_code == 200:
            res_data = response.json()
            message_id = res_data.get('id')
            print(f"✅ Email sent successfully via Resend to {to_email}. Message ID: {message_id}")
            
            if invoice_md_path:
                update_invoice_metadata(invoice_md_path, message_id=message_id, status="sent", body_text=body_text)
            return True
        else:
            print(f"❌ Resend API Error: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"❌ Failed to send email via Resend: {e}")
        return False

def send_email(to_email, subject, body_text, attachment_path=None, invoice_md_path=None):
    if os.getenv("RESEND_API_KEY"):
        return send_email_resend(to_email, subject, body_text, attachment_path, invoice_md_path)
    else:
        print("⚠️ RESEND_API_KEY not found. Falling back to SMTP.")
        return send_email_smtp(to_email, subject, body_text, attachment_path, invoice_md_path)

def build_email(invoice_md_path, send_act=False):
    """
    Формирует subject + body + метаданные для письма по счёту.
    НЕ отправляет — чистая функция для превью и переиспользования.

    Возвращает dict:
      {client_email, contact_name, client_name, subject, body,
       pdf_path, amount, period, invoice_number, items, send_act}
    Возвращает None при ошибке (нет клиента/email/PDF).
    """
    inv_meta, content = parse_frontmatter(invoice_md_path)
    if not inv_meta:
        print("❌ Failed to parse valid frontmatter from the document.")
        return None

    client_link = inv_meta.get('client')
    if not client_link:
        print("❌ Client link not found in standard metadata.")
        return None

    client_path = find_client_file(client_link)
    if not client_path:
        print(f"❌ Could not find client file for {client_link}")
        return None

    client_meta, client_content = parse_frontmatter(client_path)
    client_email = client_meta.get('email')
    client_name = client_meta.get('company_name') or client_link.replace('[[', '').replace(']]', '')

    period = inv_meta.get('period', 'текущий период')
    invoice_number = inv_meta.get('invoice_number', '')
    amount = inv_meta.get('amount', '0')
    items = inv_meta.get('items', [])

    pdf_path = extract_pdf_path(inv_meta, content, is_act=send_act)

    # Build dynamic message (custom_message из frontmatter или описаний продуктов)
    custom_message = inv_meta.get('message')
    if not custom_message:
        for item in items:
            if isinstance(item, str):
                match = re.search(r'\[\[(.*?)\]\]', item)
                if match:
                    desc = get_product_description(match.group(1))
                    if desc:
                        if custom_message:
                            custom_message += ". " + desc
                        else:
                            custom_message = desc
    if not custom_message and period != 'текущий период':
        custom_message = f"Работы за период: {period}"

    contact_name = client_meta.get('contact_name') or client_name

    # Рендерим шаблон из файла (90_Templates/tpl_*.md)
    try:
        import sys as _sys
        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from template_utils import render_template
        tpl_name = "act_email" if send_act else "invoice_email"
        variables = {
            "invoice_number": invoice_number,
            "amount": amount,
            "period": period,
            "client_name": client_name,
            "contact_name": contact_name,
            "custom_message": custom_message or "",
            "items": "; ".join(str(i) for i in items) if items else "",
        }
        subject, body = render_template(tpl_name, variables)
    except Exception as e:
        # Fallback на жёсткий шаблон если файл шаблона недоступен
        print(f"⚠️ Шаблон не загружен ({e}), используем fallback")
        subject = f"Акт №{invoice_number} — Automata.sale" if send_act else f"Счёт №{invoice_number} — Automata.sale"
        body = f"Здравствуйте, {contact_name}!\n\nНаправляю {'акт' if send_act else 'счёт'} №{invoice_number} на сумму {amount} ₽.\n\n{custom_message or ''}"

    return {
        "client_email": client_email,
        "contact_name": contact_name,
        "client_name": client_name,
        "subject": subject,
        "body": body,
        "pdf_path": pdf_path,
        "amount": amount,
        "period": period,
        "invoice_number": invoice_number,
        "items": items,
        "send_act": send_act,
    }


def main(invoice_md_path, send_act=False):
    """Отправляет письмо (использует build_email для формирования)."""
    data = build_email(invoice_md_path, send_act=send_act)
    if data is None:
        sys.exit(1)

    if not data["client_email"] or str(data["client_email"]).strip() == '':
        print(f"❌ No email address found in client profile: {data['client_name']}")
        sys.exit(1)
    if not data["pdf_path"]:
        print(f"❌ PDF link not found. Ensure the {'Act' if send_act else 'Invoice'} was generated.")
        sys.exit(1)

    print(f"Preparing to send to {data['client_name']} <{data['client_email']}>...")
    send_email(data["client_email"], data["subject"], data["body"],
               data["pdf_path"], invoice_md_path)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 send_invoice_email.py <path_to_invoice.md> [--act]")
        sys.exit(1)
        
    file_path = sys.argv[1]
    send_act = len(sys.argv) > 2 and sys.argv[2] == "--act"
    
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        sys.exit(1)
        
    main(file_path, send_act)
