
from sec_guard import guard_open

import os
import sys
import re
import argparse
import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import glob

# Ensure we can import sibling scripts
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from tochka_api import TochkaAPI
import gdrive_uploader

# --- CONFIG ---
VAULT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLIENTS_DIR = os.path.join(VAULT_ROOT, "10_Clients")
INVOICES_DIR = os.path.join(VAULT_ROOT, "30_Invoices")
TEMPLATES_DIR = os.path.join(VAULT_ROOT, "90_Templates")
DOCUMENTS_DIR = os.path.join(VAULT_ROOT, "60_Documents")
TASKS_DIR = os.path.join(VAULT_ROOT, "30_Tasks")
# SMTP CONFIG (Placeholder - User should set these env vars)
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
SMTP_USER = os.environ.get("SMTP_USER", "crm@example.com")
SMTP_PASS = os.environ.get("SMTP_PASS", "")

def parse_frontmatter(file_path):
    """Parses YAML frontmatter from a markdown file."""
    try:
        with guard_open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        match = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
        if match:
            yaml_content = match.group(1)
            data = {}
            for line in yaml_content.split('\n'):
                if ':' in line:
                    key, value = line.split(':', 1)
                    data[key.strip()] = value.strip().strip('"').strip("'")
            return data, content
    except Exception as e:
        print(f"Error parsing {file_path}: {e}")
    return {}, ""

def find_clients(tags=["support", "active"]):
    """Finds clients with specific tags."""
    clients = []
    for filepath in glob.glob(os.path.join(CLIENTS_DIR, "*.md")):
        # Skip subdirectories
        if os.path.isdir(filepath):
            continue
            
        data, content = parse_frontmatter(filepath)
        file_tags = data.get("tags", "")
        
        # Handle YAML list format [tag1, tag2] or - tag
        is_match = True
        for tag in tags:
            if tag not in content: # Simple regex check for now as parsing YAML list is tricky without pyyaml 
                 # Better: Use simple string check in the header block
                 if f"- {tag}" not in content and f"[{tag}" not in content:
                     is_match = False
                     break
        
        if is_match:
            clients.append({
                "name": os.path.splitext(os.path.basename(filepath))[0],
                "path": filepath,
                "data": data,
                "content": content
            })
    return clients

def get_unbilled_tasks(client_name):
    """Finds all unbilled tech tasks for a given client."""
    tasks = []
    if not os.path.exists(TASKS_DIR):
        return tasks
    for filepath in glob.glob(os.path.join(TASKS_DIR, "*.md")):
        data, content = parse_frontmatter(filepath)
        if data.get("client") == f"[[{client_name}]]" and not data.get("invoice"):
            title = os.path.splitext(os.path.basename(filepath))[0]
            title = re.sub(r'^\d{4}-\d{2}-\d{2}_', '', title).replace('_', ' ')
            tasks.append((filepath, title))
    return tasks

def get_contact_email(client_meta):
    """Finds the first contact link from the frontmatter and resolves their email."""
    contacts = client_meta.get("contacts", [])
    if isinstance(contacts, str):
        contacts = [contacts]
        
    for contact_link in contacts:
        # Expected format: "[[Contact Name]]"
        match = re.search(r'\[\[(.*?)\]\]', contact_link)
        if match:
            contact_name = match.group(1)
            contact_path = os.path.join(CLIENTS_DIR, "Contacts", f"{contact_name}.md")
            if os.path.exists(contact_path):
                data, _ = parse_frontmatter(contact_path)
                return data.get("email"), contact_name
                
    return None, None

def get_billing_period():
    """Returns current month name and year."""
    now = datetime.datetime.now()
    months = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
    return f"{months[now.month-1]} {now.year}"

def send_email(to_email, subject, html_body, files=[]):
    """Sends an email with the invoice/act links."""
    if not SMTP_PASS:
        print(f"⚠️  Skipping email to {to_email} (No SMTP_PASS set)")
        print(f"   Subject: {subject}")
        print(f"   Body Preview: {html_body[:100]}...")
        return

    msg = MIMEMultipart()
    msg['From'] = SMTP_USER
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.attach(MIMEText(html_body, 'html'))

    try:
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)
        server.quit()
        print(f"✅ Email sent to {to_email}")
    except Exception as e:
        print(f"❌ Failed to send email: {e}")

def main():
    parser = argparse.ArgumentParser(description="Billing Automation Engine")
    parser.add_argument("--invoices", action="store_true", help="Generate invoices for 1st of month")
    parser.add_argument("--acts", action="store_true", help="Generate acts for end of month")
    parser.add_argument("--dry-run", action="store_true", help="Do not send emails or create files")
    args = parser.parse_args()

    api = TochkaAPI()
    clients = find_clients()
    print(f"ℹ️  Found {len(clients)} active support clients.")

    for client in clients:
        print(f"\nProcessing {client['name']}...")
        email, contact_name = get_contact_email(client['data'])
        
        if not email:
            print(f"⚠️  No email found for {client['name']} (Contact: {contact_name})")
            continue

        # 1. Determine Product/Price
        tariff = client['data'].get("tariff", "Support")
        rate = float(client['data'].get("rate", "3000"))
        hours = float(client['data'].get("hours", "1"))
        total_amount = rate * hours
        
        # Map "Мониторинг" -> "Service_Support" (Hardcoded for now based on request)
        product_link = "[[Service_Support]]" if "Мониторинг" in tariff else f"[[{tariff}]]"
        items_list = [f'"{product_link} x{hours} @{rate}"']
        
        # Include technical work in the invoice
        unbilled_tasks = get_unbilled_tasks(client['name'])
        for filepath, task_title in unbilled_tasks:
            items_list.append(f'"Доп. работы: {task_title}"')
            
        items_yaml = "\n".join([f"  - {item}" for item in items_list])
        
        # 2. Generate/Find Invoice
        today = datetime.date.today()
        bitrix_id = client['data'].get('bitrix_id', '000')
        invoice_filename = f"Счёт №B24-{today.strftime('%m%d')}-{bitrix_id} от {today.strftime('%d.%m.%Y')} — {client['name']}.md"
        invoice_path = os.path.join(INVOICES_DIR, invoice_filename)
        
        if args.invoices:
            if not os.path.exists(invoice_path) and not args.dry_run:
                # Create Invoice MD
                with guard_open(invoice_path, 'w') as f:
                    f.write(f"""---
client: "[[{client['name']}]]"
invoice_number: "B24-{today.strftime('%m%d')}-{client['data'].get('bitrix_id', '000')}"
invoice_date: {today.strftime('%Y-%m-%d')}
amount: {total_amount}
status: unpaid
items:
{items_yaml}
---
# {os.path.splitext(invoice_filename)[0]}
""")
                print(f"✅ Created Invoice MD: {invoice_filename}")
                
                # Mark tasks as billed and link to this invoice
                invoice_link = f"[[{os.path.splitext(invoice_filename)[0]}]]"
                for filepath, task_title in unbilled_tasks:
                    with guard_open(filepath, 'r', encoding='utf-8') as tf:
                        tf_text = tf.read()
                    if "invoice:" in tf_text:
                        tf_text = re.sub(r'invoice:.*', f'invoice: "{invoice_link}"', tf_text)
                    else:
                        tf_text = tf_text.replace("---\n", f"---\ninvoice: \"{invoice_link}\"\n", 1)
                    with guard_open(filepath, 'w', encoding='utf-8') as tf:
                        tf.write(tf_text)
                if unbilled_tasks:
                    print(f"   🔗 Linked {len(unbilled_tasks)} tasks to invoice.")
                
                # API Call to Tochka
                print("   Requesting Invoice from Tochka...")
                # Assuming tochka_api.create_invoice handles everything logic
                # We need to call it slightly differently or shell out
                # For simplicity, calling the method directly if possible or creating a new instance
                try:
                    # Parse it again to get the dict needed by create_invoice? 
                    # Actually create_invoice takes a file path.
                    api.create_invoice(invoice_path)
                except Exception as e:
                    print(f"❌ Error creating invoice in Tochka: {e}")
            
            # 3. Upload Invoice PDF
            # Check if PDF exists
            inv_data = {}
            if os.path.exists(invoice_path):
                inv_data, _ = parse_frontmatter(invoice_path)
            
            invoice_filename = inv_data.get("invoice_pdf")
            pdf_link = ""
            
            if invoice_filename:
                pdf_path = os.path.join(DOCUMENTS_DIR, invoice_filename)
                if os.path.exists(pdf_path):
                    print(f"   Uploading Invoice PDF to GDrive...")
                    pdf_link = gdrive_uploader.upload_to_client_folder(client['name'], pdf_path, invoice_filename)
            
            # 4. Send Email (Invoice Only)
            if pdf_link and not args.dry_run:
                with guard_open(os.path.join(TEMPLATES_DIR, "email_billing_notification.html"), 'r') as f:
                    template = f.read()
                
                # Fill template
                body = template.replace("{{invoice_number}}", inv_data.get("invoice_number", "DRAFT"))
                body = body.replace("{{invoice_date}}", inv_data.get("invoice_date", str(today)))
                body = body.replace("{{month_year}}", get_billing_period())
                body = body.replace("{{amount}}", rate)
                body = body.replace("{{invoice_link}}", pdf_link)
                body = body.replace("{% if invoice_link %}", "").replace("{% endif %}", "")
                # Hide act link
                body = re.sub(r'{% if act_link %}.*?{% endif %}', '', body, flags=re.DOTALL)
                
                send_email(email, f"Счёт на оплату: {get_billing_period()}", body)

        if args.acts:
            # Find Invoice for current month
            search_prefix = f"Счёт №B24-{today.strftime('%m%y')}" # Short year for invoice number?
            # Wait, invoice generation used today.strftime('%m%d')...
            # Let's search by filename pattern for this month
            current_month_pattern = f"Счёт №B24-* от *{today.strftime('.%m.%Y')} — {client['name']}.md"
            found_invoices = glob.glob(os.path.join(INVOICES_DIR, current_month_pattern))
            
            if not found_invoices:
                print(f"⚠️  No invoice found for {client['name']} this month. Skipping Act.")
                continue
                
            invoice_path = found_invoices[0]
            print(f"   Found invoice: {os.path.basename(invoice_path)}")
            
            # Generate Act
            if not args.dry_run:
                try:
                    api.create_act(invoice_path) # This updates the MD with Act Link
                except Exception as e:
                    print(f"❌ Error creating Act: {e}")
            
            # Upload Act PDF
            # Parse MD to find act_pdf property
            inv_data, _ = parse_frontmatter(invoice_path)
            
            act_filename = inv_data.get("act_pdf")
            act_link_gdrive = ""
            
            if act_filename:
                local_act_path = os.path.join(DOCUMENTS_DIR, act_filename)
                if os.path.exists(local_act_path):
                     act_link_gdrive = gdrive_uploader.upload_to_client_folder(client['name'], local_act_path, act_filename)
            
            # Send Email (Act)
            if act_link_gdrive and not args.dry_run:
                with guard_open(os.path.join(TEMPLATES_DIR, "email_billing_notification.html"), 'r') as f:
                    template_content = f.read()
                
                # Fill template
                body = template_content
                body = body.replace("{{invoice_number}}", inv_data.get("invoice_number", "UNKNOWN"))
                body = body.replace("{{invoice_date}}", inv_data.get("invoice_date", str(today)))
                body = body.replace("{{month_year}}", get_billing_period())
                body = body.replace("{{amount}}", rate)
                
                # Handle Invoice Link (Optional: send it again?)
                # If we have it stored... maybe look for it in MD?
                # For now, let's just enable the Act link
                body = body.replace("{% if act_link %}", "").replace("{% endif %}", "")
                body = body.replace("{{act_link}}", act_link_gdrive)
                body = body.replace("{{act_date}}", datetime.date.today().strftime("%d.%m.%Y")) # Today is act date

                # Disable Invoice link if not available
                body = re.sub(r'{% if invoice_link %}.*?{% endif %}', '', body, flags=re.DOTALL)
                
                send_email(email, f"Акт выполненных работ: {get_billing_period()}", body)


if __name__ == "__main__":
    main()
