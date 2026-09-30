import os
import re
import yaml
import sys
import datetime
import requests
from tochka_api import TOCHKA_TOKEN

# --- CONFIGURATION ---
BASE_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INVOICES_DIR = os.path.join(BASE_PATH, "30_Invoices")

API_BASE_URL = "https://enter.tochka.com/uapi/invoice/v1.0"

def parse_frontmatter(file_path):
    try:
         with open(file_path, 'r', encoding='utf-8') as f:
             content = f.read()
         match = re.search(r'^\s*---\n(.*?)\n---', content, re.DOTALL)
         if match:
             return yaml.safe_load(match.group(1)), content
    except Exception as e:
         pass
    return {}, ""

def check_bill_exists(bill_id, session):
    url = f"{API_BASE_URL}/bills/{bill_id}"
    headers = {
        "Authorization": f"Bearer {TOCHKA_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    try:
        print(f"    [API] Checking {bill_id}...")
        resp = session.get(url, headers=headers, timeout=3)
        if resp.status_code == 200:
            return True, resp.json().get('Data', {}).get('Bill', {})
        return False, None
    except Exception as e:
        print(f"    [API Error] {e}")
        return False, None

def main():
    print("🚀 Starting Reconciliation...")
    print("ℹ️ Tochka API does not support downloading a full list of bills (HTTP 501 Not Implemented).")
    print("ℹ️ We will verify your local invoices against the bank one by one.\n")
    
    local_invoices = []
    local_numbers = {}
    
    for fname in os.listdir(INVOICES_DIR):
        if not fname.endswith(".md"): continue
        file_path = os.path.join(INVOICES_DIR, fname)
        meta, content = parse_frontmatter(file_path)
        
        local_invoices.append({"file": fname, "meta": meta})
        
        num = meta.get('invoice_number')
        if num:
            if num not in local_numbers:
                 local_numbers[num] = []
            local_numbers[num].append(fname)
            
    # Check Local for duplicates
    print("--- 1. Checking Local Duplicates ---")
    dup_local = {k:v for k,v in local_numbers.items() if len(v) > 1}
    if dup_local:
        for num, files in dup_local.items():
            print(f"⚠️ Duplicate Local Invoice Number '{num}' found {len(files)} times:")
            for f in files:
                 print(f"    - {f}")
    else:
        print("✅ No duplicate invoice numbers found locally.")
        
    print("\n--- 2. Verifying Linked Invoices in Tochka ---")
    session = requests.Session()
    session.trust_env = False
    
    missing_in_tochka = []
    unlinked_locally = []
    verified_count = 0
    
    for inv in local_invoices:
        meta = inv["meta"]
        fname = inv["file"]
        inv_id = meta.get('invoice_id')
        
        if not inv_id:
            unlinked_locally.append(fname)
        else:
            exists, bill_data = check_bill_exists(inv_id, session)
            if exists:
                verified_count += 1
            else:
                missing_in_tochka.append((fname, inv_id))
                
    print(f"✅ Verified {verified_count} invoices successfully match with Tochka Bank.")
    
    if missing_in_tochka:
        print(f"\n❌ Found {len(missing_in_tochka)} local invoices linking to non-existent Tochka IDs:")
        for fname, inv_id in missing_in_tochka:
            print(f"  - {fname} (ID: {inv_id})")
            
    if unlinked_locally:
         print(f"\n⚠️ Found {len(unlinked_locally)} local invoices with NO Tochka ID (Drafts / Not Sent):")
         for fname in unlinked_locally:
             print(f"  - {fname}")

if __name__ == "__main__":
    main()
