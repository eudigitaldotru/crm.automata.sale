
import os
import subprocess
import yaml
import re

INVOICES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "30_Invoices")
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))

def parse_status(file_path):
    """Checks if the invoice status is 'unpaid'."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        match = re.search(r'^\s*---\n(.*?)\n---', content, re.DOTALL)
        if match:
            meta = yaml.safe_load(match.group(1))
            return meta.get('status', '').lower() == 'unpaid'
    except Exception as e:
        print(f"Error parsing {file_path}: {e}")
    return False

def resend_invoice(invoice_path):
    print(f"\n🚀 Resending: {os.path.basename(invoice_path)}")
    
    # 1. Send Email
    email_script = os.path.join(SCRIPTS_DIR, "send_invoice_email.py")
    print(f"--- Sending Email ---")
    try:
        subprocess.run(["python3", email_script, invoice_path], check=True)
    except subprocess.CalledProcessError as e:
        print(f"❌ Email failed for {invoice_path}")

    # 2. Send Telegram
    tg_script = os.path.join(SCRIPTS_DIR, "send_invoice_tg.py")
    print(f"--- Sending Telegram ---")
    try:
        subprocess.run(["python3", tg_script, invoice_path], check=True)
    except subprocess.CalledProcessError as e:
        print(f"❌ Telegram failed for {invoice_path}")

import time

def main():
    if not os.path.exists(INVOICES_DIR):
        print(f"Error: Invoices directory not found at {INVOICES_DIR}")
        return

    unpaid_invoices = []
    for fname in os.listdir(INVOICES_DIR):
        if fname.endswith(".md"):
            path = os.path.join(INVOICES_DIR, fname)
            if parse_status(path):
                unpaid_invoices.append(path)

    print(f"Found {len(unpaid_invoices)} unpaid invoices.")
    
    for inv_path in unpaid_invoices:
        resend_invoice(inv_path)
        print("⏳ Waiting 3 seconds before next resend...")
        time.sleep(3)

    print("\n✅ All resend attempts completed.")

if __name__ == "__main__":
    main()
