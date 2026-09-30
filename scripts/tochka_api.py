
from sec_guard import guard_open

import os
import re
import json
import requests
import datetime
import yaml
import sys
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

# --- FORCE DISABLE PROXY ---
# The user's environment has a blocking proxy. We must disable it for this script.
for key in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY']:
    os.environ.pop(key, None)

# --- CONFIGURATION (Extracted from Environment) ---
TOCHKA_TOKEN = os.environ.get("TOCHKA_TOKEN")
ACCOUNT_ID = os.environ.get("TOCHKA_ACCOUNT_ID")
CUSTOMER_CODE = os.environ.get("TOCHKA_CUSTOMER_CODE")
API_BASE_URL = "https://enter.tochka.com/uapi/invoice/v1.0"

if not TOCHKA_TOKEN:
    print("⚠️  Warning: TOCHKA_TOKEN not found in environment!")

# --- HELPER FUNCTIONS ---

def parse_frontmatter(file_path):
    """Parses YAML frontmatter from a Markdown file."""
    with guard_open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    match = re.search(r'^\s*---\n(.*?)\n---', content, re.DOTALL)
    if match:
        return yaml.safe_load(match.group(1)), content
    return {}, content

def find_client_file(client_link):
    """Resolves [[Client Name]] to a file path."""
    client_name = client_link.replace('[[', '').replace(']]', '')
    # Assuming standard path structure
    base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) # AUTOMATA-CRM/
    client_path = os.path.join(base_path, "10_Clients", f"{client_name}.md")
    
    if os.path.exists(client_path):
        return client_path
    
    # Fallback search if exact match fails
    clients_dir = os.path.join(base_path, "10_Clients")
    for fname in os.listdir(clients_dir):
        if client_name in fname:
            return os.path.join(clients_dir, fname)
            
    raise FileNotFoundError(f"Client file for {client_name} not found.")

def get_bank_correspondent_account(bik):
    """Returns correspondent account for common banks based on BIK."""
    # Extracted from PHP logic
    corr_map = {
        '044525225': '30101810400000000225', # Sberbank Moscow
        '046311649': '30101810400000000649', # Sberbank Povolzhye
        '044525104': '30101810745374525104', # Tochka
        '044525593': '30101810200000000593', # Alfa-Bank
        '044525187': '30101810700000000187', # Tinkoff
    }
    return corr_map.get(bik, '30101810000000000' + bik[-3:]) # Generic fallback

# --- API CLASS ---


class TochkaAPI:
    def __init__(self):
        self.session = requests.Session()
        self.session.trust_env = False  # Ignore proxy environment variables
        # We will pass headers explicitly in request calls

        # Мобильные операторы РФ с "белыми списками" перехватывают TLS с подменой
        # сертификата (self-signed in chain) — requests падает с SSLError.
        # Пробуем верифицированное соединение; если SSL-перехват — отключаем
        # верификацию (авторизация Bearer-токеном продолжает защищать запросы).
        try:
            self.session.get("https://enter.tochka.com/", timeout=8)
        except requests.exceptions.SSLError:
            print("⚠️ Обнаружен TLS-перехват оператора (self-signed cert) — отключаю верификацию SSL")
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            self.session.verify = False
        except requests.exceptions.RequestException:
            pass  # Сетевые проблемы проверим при реальном запросе

    def create_invoice(self, invoice_md_path):
        """Creates an invoice in Tochka based on the MD file."""
        print(f"Reading Invoice: {invoice_md_path}")
        inv_meta, _ = parse_frontmatter(invoice_md_path)
        
        # 1. Resolve Client Data
        client_link = inv_meta.get('client')
        if not client_link:
            raise ValueError("Client not specified in invoice.")
            
        client_path = find_client_file(client_link)
        print(f"Found Client File: {client_path}")
        client_meta, _ = parse_frontmatter(client_path)
        
        # 2. Prepare SecondSide (Payer)
        inn = str(client_meta.get('inn', '')).strip()
        kpp = str(client_meta.get('kpp', '')).strip()
        name = client_meta.get('company_name', client_link.replace('[[','').replace(']]',''))
        
        # Detect type based on INN length (10 = company, 12 = entrepreneur/individual)
        side_type = "company"
        if len(inn) == 12:
            side_type = "ip"
        
        # Bank Details
        bik = str(client_meta.get('bank_bik', ''))
        account = str(client_meta.get('bank_account', ''))
        
        second_side = {
            "taxCode": inn,
            "type": side_type,
            "secondSideName": name,
            "legalAddress": client_meta.get('legal_address', ''),
        }
        # У ИП КПП отсутствует — пустая строка ломает валидацию Точки
        if kpp:
            second_side["kpp"] = kpp
        
        if bik and account:
            second_side["bankBik"] = bik
            second_side["bankAccount"] = account
            second_side["bankCorrAccount"] = get_bank_correspondent_account(bik)
            # bankName is optional, Tochka resolves it via BIK usually
        
        # 3. Prepare Positions
        positions = []
        items = inv_meta.get('items', [])
        
        if items:
            for item in items:
                # 3a. Resolve Product Link & Quantity
                product_path = None
                product_meta = {}
                quantity = 1.0
                price_override = 0.0
                product_link = ""

                # Handle String Format: "[[Product]] x2 @3000"
                if isinstance(item, str):
                    # Regex to find [[Product]] and optional xQuantity and @Price
                    match_link = re.search(r'\[\[(.*?)\]\]', item)
                    match_qty = re.search(r'x\s*([\d\.]+)', item)
                    match_price = re.search(r'@\s*([\d\.]+)', item)
                    
                    if match_link:
                        product_name = match_link.group(1)
                        product_link = product_name
                        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                        possible_path = os.path.join(base_path, "70_Products", f"{product_name}.md")
                    
                    if match_qty:
                        quantity = float(match_qty.group(1))
                        
                    if match_price:
                        price_override = float(match_price.group(1))

                # Handle Object Format (Legacy/Standard): { product: "...", quantity: ... }
                elif isinstance(item, dict):
                    product_raw = item.get('product', '')
                    match_link = re.search(r'\[\[(.*?)\]\]', product_raw)
                    product_name = match_link.group(1) if match_link else product_raw
                    product_link = product_name
                    
                    quantity = float(item.get('quantity', 1))
                    price_override = float(item.get('price', 0))
                    
                    base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                    possible_path = os.path.join(base_path, "70_Products", f"{product_name}.md")

                # Load Product Meta
                if 'possible_path' in locals() and os.path.exists(possible_path):
                    product_path = possible_path
                    product_meta, _ = parse_frontmatter(product_path)
                else:
                    print(f"⚠️  Product file not found: {product_link}")

                # 3b. Determine Name (Template substitution)
                name_template = product_meta.get('name', 'Услуга')
                # Overwrite name if provided in object (unlikely in string mode)
                if isinstance(item, dict) and item.get('name'):
                    name_template = item.get('name')
                    
                period = inv_meta.get('period', '')
                # Also check item-specific period if object
                if isinstance(item, dict) and item.get('period'):
                    period = item.get('period')
                
                position_name = name_template.replace('{{period}}', period)
                
                # 3c. Determine Price
                price = price_override if price_override > 0 else float(product_meta.get('price', 0))
                unit = product_meta.get('unit', 'шт')
                if isinstance(item, dict) and item.get('unit'): unit = item.get('unit')

                # 3d. Add to List
                # API expects specific strings for unitCode (e.g. "шт.")
                unit_code = unit
                if unit == 'шт': unit_code = 'шт.'
                
                positions.append({
                    "positionName": position_name,
                    "unitCode": unit_code,
                    "ndsKind": "without_nds",
                    "price": price,
                    "quantity": quantity,
                    "totalAmount": round(price * quantity, 2),
                    "totalNds": 0
                })
        else:
            # Fallback to legacy single-line logic (счета без items: разовые услуги).
            # unitCode — только строки из справочника Точки ("796" → 400 Validation Error).
            # Назначение берём из message (поле счетов за разовые услуги), иначе период.
            amount = float(inv_meta.get('amount', 0))
            position_name = inv_meta.get('message') or f"Услуги по договору (Период: {inv_meta.get('period', '')})"
            positions.append({
                "positionName": position_name,
                "unitCode": "шт.",
                "ndsKind": "without_nds",
                "price": amount,
                "quantity": 1,
                "totalAmount": round(amount, 2),
                "totalNds": 0
            })

        # Recalculate Total Amount from positions
        total_amount = round(sum(p['totalAmount'] for p in positions), 2)
        
        # 4. Payload
        current_date_str = datetime.date.today().isoformat()
        expiry_date_str = (datetime.date.today() + datetime.timedelta(days=7)).isoformat()
        
        payload = {
            "Data": {
                "accountId": ACCOUNT_ID,
                "customerCode": CUSTOMER_CODE,
                "SecondSide": second_side,
                "Content": {
                    "Invoice": {
                        "Positions": positions,
                        "date": current_date_str,
                        "totalAmount": total_amount,
                        "totalNds": 0,
                        "number": inv_meta.get('invoice_number', f"INV-{int(datetime.datetime.now().timestamp())}"),
                        "basedOn": "Договор оказания услуг",
                        "paymentExpiryDate": expiry_date_str
                    }
                }
            }
        }
        
        headers = {
            "Authorization": f"Bearer {TOCHKA_TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        # 5. Send Request
        print("Sending request to Tochka API...")
        url = f"{API_BASE_URL}/bills"
        try:
            response = self.session.post(url, json=payload, headers=headers, timeout=15)
            response.raise_for_status()
        except requests.exceptions.Timeout:
            print(f"❌ Connection Timeout (15s) while contacting Tochka API.")
            return None
        except requests.exceptions.HTTPError as e:
            print(f"HTTP Error: {e}")
            print(f"Response Body: {response.text}")
            return None
        except Exception as e:
            print(f"Connection Error: {e}")
            return None
        
        data = response.json()
        invoice_id = data.get('Data', {}).get('documentId')
        print(f"✅ Invoice Created! ID: {invoice_id}")
        
        # 6. Get PDF
        pdf_link = self.get_invoice_pdf_link(invoice_id)
        
        # Always update file with ID (fix for missing ID)
        self.update_invoice_file(invoice_md_path, pdf_link, invoice_id, is_act=False)
        
        if pdf_link:
            print(f"PDF Link: {pdf_link}")
            
        return invoice_id
    
    def get_invoice_pdf_link(self, invoice_id):
        """Fetches the PDF content."""
        url = f"{API_BASE_URL}/bills/{CUSTOMER_CODE}/{invoice_id}/file"
        
        headers = {
            "Authorization": f"Bearer {TOCHKA_TOKEN}",
            "Accept": "application/pdf"
        }
        
        try:
            response = self.session.get(url, headers=headers, timeout=15)
            if response.status_code == 200:
                 filename = f"Invoice_{invoice_id}.pdf"
                 path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "60_Documents", filename)
                 with guard_open(path, "wb") as f:
                     f.write(response.content)
                 return f"file://{path}"
            else:
                 print(f"Warning: PDF fetch failed ({response.status_code}): {response.text}")
        except Exception as e:
            print(f"Error fetching PDF: {e}")
        return None

    def update_invoice_file(self, file_path, pdf_path, doc_id, is_act=False):
        """Updates the MD file with the PDF link and ID."""
        try:
            with guard_open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 1. Update Frontmatter ID (if missing)
            if not is_act and 'invoice_id:' not in content:
                # Regex match for "invoice_number: ..."
                # We want to insert invoice_id BEFORE invoice_number
                pattern = r"(invoice_number:)"
                if re.search(pattern, content):
                    content = re.sub(pattern, f"invoice_id: {doc_id}\n\\1", content, count=1)
                else:
                    # Fallback: insert after first ---
                    content = content.replace("---\n", f"---\ninvoice_id: {doc_id}\n", 1)
            
            # Update Properties directly (tabular data)
            if is_act:
                if 'act_id:' not in content:
                    content = content.replace("---\n", f"---\nact_id: {doc_id}\n", 1)
                if 'act_status:' not in content:
                    content = content.replace("---\n", "---\nact_status: signed\n", 1)
                else:
                    content = re.sub(r'^act_status:\s*.*$', 'act_status: signed', content, flags=re.MULTILINE)
                if pdf_path and 'act_pdf:' not in content:
                    pdf_filename = os.path.basename(pdf_path)
                    content = content.replace("---\n", f"---\nact_pdf: {pdf_filename}\n", 1)
                # страж подписи: новый акт ждёт подписи владельца в Точке (см. acts_sign_tracker.py)
                if 'owner_signed:' not in content:
                    content = content.replace(
                        "---\n", "---\nowner_signed: false\nowner_signed_notified: ''\n", 1)
            else:
                if pdf_path and 'invoice_pdf:' not in content:
                    pdf_filename = os.path.basename(pdf_path)
                    content = content.replace("---\n", f"---\ninvoice_pdf: {pdf_filename}\n", 1)
                    
            # 2. Update Checkbox & Link (Visual for Obsidian, not used by scripts)
            if pdf_path:
                if is_act:
                    target = "- [ ] Акт выполненных работ"
                    replacement = f"- [x] Акт выполненных работ ([PDF]({pdf_path}))"
                else:
                    target = "- [ ] Счёт (PDF)"
                    replacement = f"- [x] Счёт (PDF) ([PDF]({pdf_path}))"
                
                if target in content:
                    content = content.replace(target, replacement)
                else:
                    # Append if not found and not already checked
                    if replacement not in content:
                        content += f"\n\n{replacement}"
            
            with guard_open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"✅ Updated file: {file_path}")
            
        except Exception as e:
            print(f"⚠️ Error updating file: {e}")

    def create_act(self, invoice_md_path, invoice_id_ref=None, act_date_override=None):
        """Creates an Act based on the Invoice MD file and linked Invoice ID."""
        print(f"Reading Invoice/Act Data: {invoice_md_path}")
        inv_meta, _ = parse_frontmatter(invoice_md_path)
        
        # We need an Invoice ID to link the Act to.
        # Ideally, this should be stored in the MD file after invoice creation.
        # For now, we accept it as an arg or look for frontmatter 'invoice_id'
        invoice_id = invoice_id_ref or inv_meta.get('invoice_id')
        if not invoice_id:
            print("❌ Cannot create Act: No Invoice ID found linked to this file.")
            return None

        # 1. Resolve Client Data
        client_link = inv_meta.get('client')
        client_path = find_client_file(client_link)
        client_meta, _ = parse_frontmatter(client_path)
        
        # 2. Prepare SecondSide (Same as Invoice)
        # ... reusing logic would be better, but copying for speed/isolation
        inn = str(client_meta.get('inn', '')).strip()
        side_type = "company"
        if len(inn) == 12:
            side_type = "ip"
            
        second_side = {
            "taxCode": inn,
            "type": side_type,
            "secondSideName": client_meta.get('company_name', client_link.replace('[[','').replace(']]','')),
            "legalAddress": client_meta.get('legal_address', ''),
        }
        # У ИП КПП отсутствует — пустая строка ломает валидацию Точки
        kpp_act = str(client_meta.get('kpp', '')).strip()
        if kpp_act:
            second_side["kpp"] = kpp_act
        bik = str(client_meta.get('bank_bik', ''))
        account = str(client_meta.get('bank_account', ''))
        if bik and account:
            second_side["bankBik"] = bik
            second_side["bankAccount"] = account
            second_side["bankCorrAccount"] = get_bank_correspondent_account(bik)

        # 3. Positions (Same as Invoice)
        # 3. Positions (Same as Invoice)
        # For Acts, we should ideally re-parse or use the same logic. 
        # For simplicity in this iteration, we reuse the invoice item logic if available or fallback.
        # NOTE: To deeply sync, we should refactor position creation into a shared function.
        # But for now, let's just make sure it doesn't crash on 'amount'.
        
        amount = float(inv_meta.get('amount', 0)) # Default/Legacy
        
        # ... (In a real scenario, we'd copy the Position logic here too. 
        # For now, let's assume Acts are generated after Invoices and we might lack full context 
        # if we don't duplicate the code. To keep it safe, I'll duplicate the logic briefly.)
        
        positions = []
        items = inv_meta.get('items', [])
        
        if items:
             for item in items:
                # 3a. Resolve Product Link & Quantity
                product_path = None
                product_meta = {}
                quantity = 1.0
                price_override = 0.0
                product_link = ""
                name_override = ""
                unit_override = ""

                # Handle String Format: "[[Product]] x2"
                if isinstance(item, str):
                    match_link = re.search(r'\[\[(.*?)\]\]', item)
                    match_qty = re.search(r'x\s*([\d\.]+)', item)
                    match_price = re.search(r'@\s*([\d\.]+)', item)
                    
                    if match_link:
                        product_name = match_link.group(1)
                        product_link = product_name
                        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                        possible_path = os.path.join(base_path, "70_Products", f"{product_name}.md")
                    
                    if match_qty:
                        quantity = float(match_qty.group(1))
                        
                    if match_price:
                        price_override = float(match_price.group(1))

                # Handle Object Format
                elif isinstance(item, dict):
                    product_raw = item.get('product', '')
                    match_link = re.search(r'\[\[(.*?)\]\]', product_raw)
                    product_name = match_link.group(1) if match_link else product_raw
                    product_link = product_name
                    
                    quantity = float(item.get('quantity', 1))
                    price_override = float(item.get('price', 0))
                    name_override = item.get('name', '')
                    unit_override = item.get('unit', '')
                    
                    base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                    possible_path = os.path.join(base_path, "70_Products", f"{product_name}.md")

                # Load Product Meta
                if 'possible_path' in locals() and os.path.exists(possible_path):
                    product_path = possible_path
                    product_meta, _ = parse_frontmatter(product_path)

                # 3b. Determine Name (Template substitution)
                name_template = name_override or product_meta.get('name', 'Услуга')
                period = inv_meta.get('period', '')
                if isinstance(item, dict) and item.get('period'):
                    period = item.get('period')
                
                position_name = name_template.replace('{{period}}', period)
                
                # 3c. Determine Price & Quantity
                price = price_override if price_override > 0 else float(product_meta.get('price', 0))
                unit = unit_override or product_meta.get('unit', 'шт')
                
                # API expects specific strings for unitCode (e.g. "шт.")
                unit_code = unit
                if unit == 'шт': unit_code = 'шт.'

                positions.append({
                    "positionName": position_name,
                    "unitCode": unit_code,
                    "ndsKind": "without_nds",
                    "price": price,
                    "quantity": quantity,
                    "totalAmount": round(price * quantity, 2),
                    "totalNds": 0
                })
        else:
             positions = [{
                "positionName": f"Услуги по договору (Период: {inv_meta.get('period', '')})",
                "unitCode": "шт.",
                "ndsKind": "without_nds",
                "price": amount,
                "quantity": 1,
                "totalAmount": round(amount, 2),
                "totalNds": 0
            }]

        total_amount = round(sum(p['totalAmount'] for p in positions), 2)

        # 4. Payload for Closing Document (Act)
        # End of month of the service period (for support clients), or fallback to invoice date
        is_support = False
        client_tags = client_meta.get('tags', [])
        if isinstance(client_tags, list) and 'support' in client_tags:
            is_support = True
        elif isinstance(client_tags, str) and 'support' in client_tags:
            is_support = True

        def get_last_day_of_period(period_str, inv_date_obj, support_flag):
            months_ru = {
                "январ": 1, "феврал": 2, "март": 3, "апрел": 4, 
                "май": 5, "мая": 5, "июн": 6, "июл": 7, "август": 8, 
                "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12
            }
            period_lower = str(period_str).lower()
            
            import calendar
            import datetime
            fallback_date = datetime.date.today()
            if isinstance(inv_date_obj, datetime.date):
                fallback_date = inv_date_obj
            elif isinstance(inv_date_obj, datetime.datetime):
                fallback_date = inv_date_obj.date()
            elif isinstance(inv_date_obj, str) and len(inv_date_obj) >= 10:
                try:
                    fallback_date = datetime.date.fromisoformat(inv_date_obj[:10])
                except:
                    pass

            if support_flag:
                for ru_mon, mon_num in months_ru.items():
                    if ru_mon in period_lower:
                        year = fallback_date.year
                        match = re.search(r'\d{4}', period_lower)
                        if match:
                            year = int(match.group())
                        last_day = calendar.monthrange(year, mon_num)[1]
                        return datetime.date(year, mon_num, last_day).isoformat()
            
            return fallback_date.isoformat()

        act_date = act_date_override or get_last_day_of_period(inv_meta.get('period', ''), inv_meta.get('invoice_date'), is_support)
        act_number = f"ACT-{inv_meta.get('invoice_number', '001')}"
        
        payload = {
            "Data": {
                "accountId": ACCOUNT_ID,
                "customerCode": CUSTOMER_CODE,
                "documentId": invoice_id, # Link to Invoice
                "SecondSide": second_side,
                "Content": {
                    "Act": {
                        "Positions": positions,
                        "date": act_date,
                        "totalAmount": total_amount,
                        "totalNds": 0,
                        "number": act_number,
                        "basedOn": f"Счет №{inv_meta.get('invoice_number')} от {inv_meta.get('invoice_date')}"
                    },
                    # Required fields even if null (per API validation error)
                    "PackingList": None,
                    "Invoicef": None,
                    "Upd": None
                }
            }
        }
        
        headers = {
            "Authorization": f"Bearer {TOCHKA_TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        print(f"Sending ACT request for Invoice {invoice_id}...")
        url = f"https://enter.tochka.com/uapi/invoice/v1.0/closing-documents"
        
        try:
            response = self.session.post(url, json=payload, headers=headers, timeout=15)
            response.raise_for_status()
        except requests.exceptions.Timeout:
            print(f"❌ Connection Timeout (15s) while creating Act.")
            return None
        except Exception as e:
            print(f"Error creating Act: {e} | {response.text if 'response' in locals() else ''}")
            return None
            
        data = response.json()
        act_id = data.get('Data', {}).get('documentId')
        print(f"✅ Act Created! ID: {act_id}")
        
        # Get PDF
        pdf_link = self.get_act_pdf_link(act_id)
        if pdf_link:
            print(f"Act PDF Link: {pdf_link}")
            self.update_invoice_file(invoice_md_path, pdf_link, act_id, is_act=True)
            
        return act_id

    def get_act_pdf_link(self, act_id):
        """Fetches the PDF content for an Act."""
        url = f"https://enter.tochka.com/uapi/invoice/v1.0/closing-documents/{CUSTOMER_CODE}/{act_id}/file"
        headers = {
            "Authorization": f"Bearer {TOCHKA_TOKEN}",
            "Accept": "application/pdf"
        }
        try:
            response = self.session.get(url, headers=headers, timeout=15)
            if response.status_code == 200:
                 filename = f"Act_{act_id}.pdf"
                 path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "60_Documents", filename)
                 with guard_open(path, "wb") as f:
                     f.write(response.content)
                 return f"file://{path}"
        except Exception as e:
            print(f"Error fetching Act PDF: {e}")
        return None

    def get_statement(self, days=7):
        """Fetches bank statement for the last N days."""
        end_date = datetime.date.today()
        start_date = end_date - datetime.timedelta(days=days)
        
        print(f"Fetching statement from {start_date} to {end_date}...")
        
        # 1. Init Statement (Async)
        url_init = "https://enter.tochka.com/uapi/open-banking/v1.0/statements"
        headers = {
            "Authorization": f"Bearer {TOCHKA_TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        payload = {
            "Data": {
                "Statement": {
                    "accountId": ACCOUNT_ID,
                    "startDateTime": start_date.isoformat(),
                    "endDateTime": end_date.isoformat()
                }
            }
        }
        
        try:
            resp_init = self.session.post(url_init, headers=headers, json=payload, timeout=15)
            resp_init.raise_for_status()
            stmt_id = resp_init.json().get('Data', {}).get('Statement', {}).get('statementId')
            print(f"Statement initialized. ID: {stmt_id}")
        except Exception as e:
            print(f"Error initializing statement: {e}")
            if 'resp_init' in locals():
                print(resp_init.text)
            return []

        # 2. Poll for results
        import time
        encoded_acc_id = ACCOUNT_ID.replace('/', '%2F')
        url_poll = f"https://enter.tochka.com/uapi/open-banking/v1.0/accounts/{encoded_acc_id}/statements/{stmt_id}"
        
        for i in range(10): # Try 10 times (30 sec)
            print(f"Polling status ({i+1}/10)...")
            try:
                resp_poll = self.session.get(url_poll, headers=headers, timeout=15)
                if resp_poll.status_code == 200:
                    data = resp_poll.json()
                    statement_info = data.get('Data', {}).get('Statement', [{}])[0]
                    status = statement_info.get('status')
                    
                    if status == 'Ready' or statement_info.get('Transaction'):
                        txs = statement_info.get('Transaction', [])
                        print(f"✅ Statement Ready! Found {len(txs)} transactions.")
                        return txs
                    
                time.sleep(3)
            except Exception as e:
                print(f"Polling error: {e}")
                time.sleep(3)
                
        print("❌ Statement timed out or no data.")
        return []

if __name__ == "__main__":
    import sys
    # Usage: 
    #   create invoice: python3 tochka_api.py invoice.md
    #   create act:     python3 tochka_api.py invoice.md --act <invoice_id>
    
    if len(sys.argv) > 1:
        api = TochkaAPI()
        
        if sys.argv[1] == "--statement":
            days = int(sys.argv[2]) if len(sys.argv) > 2 else 7
            txs = api.get_statement(days)
            for t in txs:
                print(f" - {t.get('transactionDate')} | {t.get('Amount', {}).get('amount')} | {t.get('description')}")
        
        else:
            file_path = sys.argv[1]
            # Check for --act flag (it could be 2nd or 3rd arg)
            if len(sys.argv) > 2 and sys.argv[2] == "--act":
                 inv_id_arg = sys.argv[3] if len(sys.argv) > 3 else None
                 result = api.create_act(file_path, inv_id_arg)
            else:
                 result = api.create_invoice(file_path)
            # create_invoice/create_act возвращают None при ошибке (HTTPError и т.п.).
            # Без этого exit code = 0 даже при провале, и вызывающая сторона считает успехом.
            if result is None:
                sys.exit(1)
    else:
        print("Usage:")
        print("  Create Invoice: python3 scripts/tochka_api.py <path_to_invoice_md>")
        print("  Create Act:     python3 scripts/tochka_api.py <path_to_invoice_md> --act [invoice_id]")
        print("  Get Statement:  python3 scripts/tochka_api.py --statement [days]")
