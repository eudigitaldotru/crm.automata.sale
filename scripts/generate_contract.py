
from sec_guard import guard_open, guard_requests_post
import os
import sys
import re
import yaml
import datetime
import argparse
import subprocess

# --- CONFIGURATION ---
BASE_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLIENTS_DIR = os.path.join(BASE_PATH, "10_Clients")
TEMPLATES_DIR = os.path.join(BASE_PATH, "90_Templates")
DOCUMENTS_DIR = os.path.join(BASE_PATH, "60_Documents")
CONTRACTS_DIR = os.path.join(DOCUMENTS_DIR, "Contracts")

# Ensure Contracts directory exists
if not os.path.exists(CONTRACTS_DIR):
    os.makedirs(CONTRACTS_DIR)

import smtplib
from email.message import EmailMessage
from email.utils import formatdate
from dotenv import load_dotenv

# Load environment variables
dotenv_path = os.path.join(BASE_PATH, ".env")
load_dotenv(dotenv_path)

EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
SMTP_SERVER = "smtp.timeweb.ru"
SMTP_PORT = 465

def parse_frontmatter(file_path):
    with guard_open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    match = re.search(r'^---\n(.*?)\n---', content, re.DOTALL)
    if match:
        meta = yaml.safe_load(match.group(1))
        body = content[match.end():]
        return meta, body
    return {}, content

def extract_site_address(content):
    match = re.search(r'\*\*Домен:\*\*\s*([a-zA-Z0-9.-]+)', content)
    if match:
        return match.group(1).strip()
    return "_________________"

def generate_pdf_from_html(html_path, pdf_path):
    cmd = [
        "google-chrome",
        "--headless",
        "--disable-gpu",
        "--no-sandbox",
        f"--print-to-pdf={pdf_path}",
        html_path
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Chrome failed: {e.stderr.decode()}")
        return False

HOURS_MAP = {
    1: "один", 2: "два", 3: "три", 4: "четыре", 5: "пять",
    6: "шесть", 7: "семь", 8: "восемь", 9: "девять", 10: "десять"
}

def send_contract_email(to_email, client_name, contact_name, file_path):
    if not EMAIL_USER or not EMAIL_PASS:
        print("❌ Error: EMAIL_USER or EMAIL_PASS not found in .env file.")
        return False
        
    msg = EmailMessage()
    msg['Subject'] = f"Договор на разработку/поддержку — Automata.sale"
    msg['From'] = EMAIL_USER
    msg['To'] = to_email
    msg['Date'] = formatdate(localtime=True)
    
    # Template Option 8: Contract Sending
    body = f"Здравствуйте, {contact_name}!\n\n"
    body += "Направляю исправленный договор на сопровождение сайта (во вложении). В прошлой версии затесалась техническая ошибка со старой таблицей тарифов и SLA, сейчас всё актуализировал согласно нашим договоренностям.\n\n"
    body += "Пожалуйста, проверьте реквизиты. Если всё корректно:\n"
    body += "1. Подпишите с вашей стороны.\n"
    body += "2. Пришлите ответным письмом скан (или фото) всех страниц.\n\n"
    body += "Оригиналами можем обменяться через ЭДО (мы работаем в Контур.Диадок) или по почте — как вам удобнее?\n\n"
    body += "Жду подписанный скан, чтобы официально стартовать работы.\n\n"
    _nm = os.getenv("CRM_OWNER_NAME", "Ваше имя")
    _sig = os.getenv("CRM_OWNER_TITLE", "Ваша подпись/специализация")
    body += f"—\nС уважением,\n{_nm}\n{_sig}\n\n"
    body += ("📞 " + os.getenv("CRM_OWNER_PHONE", "+7 (000) 000-00-00") +
             "\n💬 Telegram: " + os.getenv("CRM_OWNER_TELEGRAM", "@your_handle") +
             "\n📧 " + os.getenv("CRM_OWNER_EMAIL", "you@example.com") +
             "\n🌐 " + os.getenv("CRM_OWNER_SITE", "example.com"))
    
    msg.set_content(body)
    
    if os.path.exists(file_path):
        filename = os.path.basename(file_path)
        try:
            with guard_open(file_path, 'rb') as f:
                file_data = f.read()
            import mimetypes
            ctype, encoding = mimetypes.guess_type(file_path)
            if ctype is None or encoding is not None:
                ctype = 'application/octet-stream'
            maintype, subtype = ctype.split('/', 1)
            
            msg.add_attachment(file_data, maintype=maintype, subtype=subtype, filename=filename)
            print(f"📎 Attached: {filename} as {ctype}")
        except Exception as e:
            print(f"❌ Failed to attach {file_path}: {e}")
            return False

    # Check for Resend
    api_key = os.getenv("RESEND_API_KEY")
    if api_key:
        import requests
        import base64
        url = "https://api.resend.com/emails"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        html_body = body.replace('\n', '<br>')
        payload = {
            "from": f"Automata CRM <{EMAIL_USER}>",
            "to": [to_email],
            "subject": msg['Subject'],
            "html": html_body,
            "text": body
        }
        
        if os.path.exists(file_path):
            filename = os.path.basename(file_path)
            try:
                with guard_open(file_path, 'rb') as f:
                    pdf_data = f.read()
                b64_content = base64.b64encode(pdf_data).decode('utf-8')
                payload["attachments"] = [
                    {
                        "filename": filename,
                        "content": b64_content
                    }
                ]
            except Exception as e:
                print(f"❌ Failed to attach {file_path}: {e}")
                
        try:
            print("Connecting to Resend API...")
            response = guard_requests_post(url, headers=headers, json=payload)
            if response.status_code == 200:
                print(f"✅ Email sent successfully via Resend to {to_email}")
                return True
            else:
                print(f"❌ Resend API Error: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            print(f"❌ Failed to send email via Resend: {e}")
            return False

    # Fallback to SMTP
    try:
        print(f"Connecting to {SMTP_SERVER}...")
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
            server.login(EMAIL_USER, EMAIL_PASS)
            server.send_message(msg)
        print(f"✅ Email sent successfully to {to_email}")
        return True
    except Exception as e:
        print(f"❌ Failed to send email: {e}")
        return False

def generate_contract(client_file, doc_number=None, send=False, pdf=False):
    if not os.path.exists(client_file):
        print(f"❌ Client file not found: {client_file}")
        return

    meta, content = parse_frontmatter(client_file)
    client_name = os.path.basename(client_file).replace(".md", "")
    
    template_ext = "html" if pdf else "txt"
    template_path = os.path.join(TEMPLATES_DIR, f"tpl_contract.{template_ext}")
    if not os.path.exists(template_path):
        print(f"❌ Template not found: {template_path}")
        return

    with guard_open(template_path, 'r', encoding='utf-8') as f:
        template = f.read()

    # Mapping
    today = datetime.date.today()
    doc_date = today.strftime("%d.%m.%Y")
    
    if not doc_number:
        doc_number = today.strftime("%Y%m%d") + "-" + str(meta.get('bitrix_id', '000'))

    site_address = extract_site_address(content)
    
    # Defaults and mapping (handling None)
    def clean(val, default=''):
        return str(val) if val is not None else default

    # Преамбула «Заказчик»: ИП или организация
    director = clean(meta.get('director_name') or meta.get('director'), '_________________')
    ogrn = clean(meta.get('ogrn'))
    is_ip = clean(meta.get('type')) == 'ИП' or (ogrn and len(ogrn) == 15)
    if is_ip:
        company_block = (f"**Индивидуальный предприниматель {director}** "
                         f"(ОГРНИП {ogrn}, ИНН {clean(meta.get('inn'))}), "
                         f"именуемый в дальнейшем **«Заказчик»**, действующий на основании листа записи ЕГРИП, с другой стороны,")
        ogrn_label = "ОГРНИП"
    else:
        company_block = (f"**{clean(meta.get('company_name'), client_name)}** (ОГРН {ogrn}, ИНН {clean(meta.get('inn'))}), "
                         f"именуемое в дальнейшем **«Заказчик»**, в лице {director}, действующей на основании Устава, с другой стороны,")
        ogrn_label = "ОГРН"

    incl_hours = meta.get('included_hours', 4)
    incl_hours_text = HOURS_MAP.get(incl_hours, str(incl_hours))
    def get_hours_declension(n):
        if n % 10 == 1 and n % 100 != 11:
            return "час"
        elif n % 10 in [2, 3, 4] and n % 100 not in [12, 13, 14]:
            return "часа"
        else:
            return "часов"
    hours_phrase = f"{incl_hours} ({incl_hours_text}) {get_hours_declension(incl_hours)}"

    data = {
        "{DocumentNumber}": clean(doc_number),
        "{DocumentDate}": doc_date,
        "{RequisiteRqCompanyFullName}": clean(meta.get('company_name'), client_name),
        "{RequisiteRqInn}": clean(meta.get('inn')),
        "{RequisiteRqKpp}": clean(meta.get('kpp')),
        "{RequisiteRqOgrn}": clean(meta.get('ogrn')),
        "{RequisiteRqBik}": clean(meta.get('bank_bik')),
        "{RequisiteRqAccNum}": clean(meta.get('bank_account')),
        "{LegalAddress}": clean(meta.get('legal_address')),
        "{ContactEmailMailing}": clean(meta.get('email')),
        "{TariffName}": clean(meta.get('tariff'), 'Развитие'),
        "{Rate}": clean(meta.get('rate'), '3000'),
        "{MonthlyFee}": clean(meta.get('monthly_retainer_fee'), '35000'),
        "{IncludedHours}": hours_phrase,
        "{SiteAddress}": site_address,
        "{CompanyRequisiteRqDirector}": director,
        "{RequisiteRqCompanyBlock}": company_block,
        "{RequisiteRqOgrnLabel}": ogrn_label,
        "{UfCrm4IfFioHead}": clean(meta.get('director_name') or meta.get('director'), '_________________'),
        "{UfCrm4IfPosHead}": clean(meta.get('director_pos'), 'Директор'),
        "{Date}": doc_date,
        "{ClientEmail}": clean(meta.get('email')),
        "{ClientINN}": clean(meta.get('inn')),
        "{ClientOGRN}": clean(meta.get('ogrn')),
        "{BankBIK}": clean(meta.get('bank_bik')),
        "{BankAccount}": clean(meta.get('bank_account')),
        "{DirectorName}": clean(meta.get('director_name') or meta.get('director'), '_________________'),
        "{IncludedHoursText}": incl_hours_text,
    }

    # Perform replacement
    result = template
    for key, value in data.items():
        result = result.replace(key, str(value))

    # Output file
    ext = "pdf" if pdf else "txt"
    output_filename = f"Договор №{doc_number} — {client_name}.{ext}"
    output_path = os.path.join(CONTRACTS_DIR, output_filename)
    
    if pdf:
        # Save temporary HTML then convert
        temp_html = output_path.replace(".pdf", ".temp.html")
        with guard_open(temp_html, 'w', encoding='utf-8') as f:
            f.write(result)
        
        success = generate_pdf_from_html(temp_html, output_path)
        os.remove(temp_html) # Cleanup
        if not success:
            return None
    else:
        with guard_open(output_path, 'w', encoding='utf-8') as f:
            f.write(result)
        
    print(f"✅ Contract generated: {output_path}")

    if send:
        email = meta.get('email')
        if email:
            contact_name = meta.get('contact_name') or client_name
            send_contract_email(email, client_name, contact_name, output_path)
        else:
            print("⚠️ Cannot send email: client email not found in metadata.")

    return output_path

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate contract for client")
    parser.add_argument("client_file", help="Path to client .md file")
    parser.add_argument("--number", help="Contract number")
    parser.add_argument("--send", action="store_true", help="Send the contract via email")
    parser.add_argument("--pdf", action="store_true", help="Generate PDF instead of TXT")
    args = parser.parse_args()

    client_path = args.client_file
    if not os.path.isabs(client_path):
        if not os.path.exists(client_path):
            client_path = os.path.join(CLIENTS_DIR, client_path)
    
    generate_contract(client_path, args.number, args.send, args.pdf)
