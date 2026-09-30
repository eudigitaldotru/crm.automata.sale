
from sec_guard import guard_open, guard_requests_get
import os
import re
import yaml
import sys
import datetime
import requests
from dotenv import load_dotenv
from tochka_api import TOCHKA_TOKEN

# --- CONFIGURATION ---
BASE_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_PATH, ".env"))
INVOICES_DIR = os.path.join(BASE_PATH, "30_Invoices")
ACTS_DIR = os.path.join(BASE_PATH, "35_Acts")

API_BASE_URL = "https://enter.tochka.com/uapi/invoice/v1.0"

def parse_frontmatter(file_path):
    """Parses YAML frontmatter from a Markdown file."""
    try:
         with guard_open(file_path, 'r', encoding='utf-8') as f:
             content = f.read()
         match = re.search(r'^\s*---\n(.*?)\n---', content, re.DOTALL)
         if match:
             return yaml.safe_load(match.group(1)), content
    except Exception as e:
         print(f"Error reading {file_path}: {e}")
    return {}, ""

def update_file_tags_and_status(file_path, content, old_tag, new_tag, additional_fields=None):
    """Replaces a tag in the frontmatter and adds/updates fields like payment_date."""
    # Replace tag
    new_content = content.replace(f"- {old_tag}", f"- {new_tag}")
    
    # Update status in frontmatter if present
    if "status: unpaid" in new_content and "paid" in new_tag:
        new_content = new_content.replace("status: unpaid", "status: paid")
    if "status: unsigned" in new_content and "signed" in new_tag:
        new_content = new_content.replace("status: unsigned", "status: signed")
        
    # visual block update removed based on strict tabular requirement
        
    # Add additional fields
    if additional_fields:
        for k, v in additional_fields.items():
            # If the field already exists as empty, fill it
            if f"{k}: \n" in new_content or f"{k}:\n" in new_content:
                 new_content = re.sub(rf"{k}:\s*\n", f"{k}: {v}\n", new_content)
            else:
                 # Otherwise append it before the end of frontmatter
                 new_content = new_content.replace("---\n\n#", f"{k}: {v}\n---\n\n#", 1)
                 
    try:
        with guard_open(file_path, "w", encoding="utf-8") as f:
            f.write(new_content)
        return True
    except Exception as e:
        print(f"Error updating file {file_path}: {e}")
        return False

def check_invoice_paid(invoice_id):
    """Checks the Tochka API to see if an invoice is paid."""
    if not invoice_id:
        return False
        
    url = f"{API_BASE_URL}/bills/{invoice_id}"
    headers = {
        "Authorization": f"Bearer {TOCHKA_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    try:
        resp = guard_requests_get(url, headers=headers, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            status = data.get('Data', {}).get('Bill', {}).get('status', '')
            # Statuses in Tochka usually include: 'created', 'sent', 'paid', 'partially_paid', 'cancelled'
            if status.lower() == 'paid':
                return True
        elif resp.status_code == 404:
            print(f"  ⚠️ Invoice {invoice_id} not found in Tochka Bank.")
    except Exception as e:
        print(f"  ⚠️ Error checking invoice {invoice_id}: {e}")
    return False

def check_act_signed(act_id):
    """
    Placeholder for checking Act signature status in Tochka EDoc.
    Currently assumes unsigned unless manually verified if API doesn't support direct status.
    """
    if not act_id:
        return False
    # TODO: Implement actual EDoc API call if Tochka supports Act Signature checking
    # For now, we return False to keep them unsigned until manual verification,
    # or implement polling over signature Webhooks.
    return False

def check_invoices():
    print("\n🔍 Scanning Invoices for #unpaid_invoice...")
    if not os.path.exists(INVOICES_DIR):
        print(f"Directory not found: {INVOICES_DIR}")
        return

    processed = 0
    updated = 0
    for fname in os.listdir(INVOICES_DIR):
        if not fname.endswith(".md"):
            continue
            
        file_path = os.path.join(INVOICES_DIR, fname)
        meta, content = parse_frontmatter(file_path)
        
        tags = meta.get('tags', [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",")]
            
        if 'unpaid_invoice' in tags:
            processed += 1
            print(f"  Checking {fname}...")
            # We need the invoice ID from the PDF link or meta
            invoice_id = meta.get('invoice_id')
            if not invoice_id:
                # Try extracting from PDF link
                match = re.search(r'Invoice_([a-zA-Z0-9\-]+)\.pdf', content)
                if match:
                    invoice_id = match.group(1)
            
            if invoice_id:
                is_paid = check_invoice_paid(invoice_id)
                if is_paid:
                    print(f"    ✅ Invoice is Paid! Updating tags...")
                    update_file_tags_and_status(
                        file_path, content, 
                        old_tag="unpaid_invoice", new_tag="paid_invoice",
                        additional_fields={"payment_date": datetime.date.today().strftime("%Y-%m-%d")}
                    )
                    updated += 1
                else:
                    print(f"    ⏳ Still unpaid.")
            else:
                print("    ⚠️ No Tochka Invoice ID found. Ensure it was generated via API.")
                
    print(f"✅ Invoices Check Complete. Processed: {processed}, Paid \u0026 Updated: {updated}.")

def check_acts():
    print("\n🔍 Scanning Acts for #unsigned_act...")
    if not os.path.exists(ACTS_DIR):
        return

    processed = 0
    updated = 0
    for fname in os.listdir(ACTS_DIR):
        if not fname.endswith(".md"):
            continue
            
        file_path = os.path.join(ACTS_DIR, fname)
        meta, content = parse_frontmatter(file_path)
        
        tags = meta.get('tags', [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",")]
            
        if 'unsigned_act' in tags:
            processed += 1
            print(f"  Checking {fname}...")
            # Assuming EDoc tracking needs an ID or relies on manual webhook
            # Placeholder for EDoc API call
            act_id = meta.get('act_id') 
            is_signed = check_act_signed(act_id)
            if is_signed:
                print(f"    ✅ Act is Signed! Updating tags...")
                update_file_tags_and_status(
                    file_path, content, 
                    old_tag="unsigned_act", new_tag="signed_act",
                )
                updated += 1
            else:
                print(f"    ⏳ Still unsigned (or API lookup pending).")
                
    print(f"✅ Acts Check Complete. Processed: {processed}, Signed & Updated: {updated}.")

def check_email_status(message_id):
    """Checks Resend API for email status."""
    api_key = os.getenv("RESEND_API_KEY")
    if not api_key:
        return None
        
    url = f"https://api.resend.com/emails/{message_id}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    try:
        resp = guard_requests_get(url, headers=headers, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("last_event")
    except Exception as e:
        print(f"  ⚠️ Error checking email {message_id}: {e}")
        
    return None

def update_email_status_in_file(file_path, content, new_status):
    new_content = re.sub(r'email_status:\s*.*?\n', f'email_status: {new_status}\n', content)
    try:
        with guard_open(file_path, "w", encoding="utf-8") as f:
            f.write(new_content)
        return True
    except Exception as e:
        print(f"Error updating file {file_path}: {e}")
        return False

def check_emails_in_dir(directory):
    if not os.path.exists(directory):
        return

    for fname in os.listdir(directory):
        if not fname.endswith(".md"):
            continue
            
        file_path = os.path.join(directory, fname)
        meta, content = parse_frontmatter(file_path)
        
        email_status = meta.get('email_status')
        message_id = meta.get('email_message_id')
        
        if email_status in ['sent', 'delivered'] and message_id:
            print(f"  Checking Email Status for {fname}...")
            new_status = check_email_status(message_id)
            if new_status and new_status != email_status:
                print(f"    ✉️ Status changed: {email_status} -> {new_status}")
                update_email_status_in_file(file_path, content, new_status)
            else:
                print(f"    ⏳ Status remains {email_status}")

def check_emails():
    print("\n🔍 Scanning for Email Delivery Statuses...")
    check_emails_in_dir(INVOICES_DIR)
    check_emails_in_dir(ACTS_DIR)
    print("✅ Emails Check Complete.")

def main():
    print("🚀 Starting Automatic Status Verification...")
    check_invoices()
    check_acts()
    check_emails()
    print("\n==========================================")
    print("🎉 Verification Cycle Complete.")
    print("==========================================")

if __name__ == "__main__":
    main()
