
from sec_guard import guard_open

import os
import re # Added missing import
import yaml
import datetime
from tochka_api import TochkaAPI, parse_frontmatter, find_client_file
from database import get_transaction_matched_amount, record_match, init_db

# Initialize DB on start
init_db()

INVOICES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "30_Invoices") # Adjusted path based on user context

def get_open_invoices():
    """Finds invoices with status 'Sent'."""
    invoices = []
    if not os.path.exists(INVOICES_DIR):
        # Fallback to 50_Invoices if 30 not found (user context implied 30 or 50)
        alt_dir = INVOICES_DIR.replace("30_Invoices", "50_Invoices")
        if os.path.exists(alt_dir):
            return get_open_invoices_from_dir(alt_dir)
        print(f"Warning: Invoices directory not found at {INVOICES_DIR}")
        return []
        
    return get_open_invoices_from_dir(INVOICES_DIR)

def get_open_invoices_from_dir(directory):
    invoices = []
    print(f"Scanning for open invoices in: {directory}")
    for fname in os.listdir(directory):
        if not fname.endswith(".md"):
            continue
            
        path = os.path.join(directory, fname)
        meta, content = parse_frontmatter(path)
        
        # Check status. Assuming 'Sent' or missing status means unpaid.
        status = meta.get('status', 'Sent')
        pay_date = meta.get('payment_date')
        if status.lower() in ['sent', 'awaiting_payment', 'new', 'unpaid'] or (status.lower() == 'paid' and not pay_date):
            # Resolve Client INN for matching
            client_inn = None
            client_link = meta.get('client')
            if client_link:
                try:
                    c_path = find_client_file(client_link)
                    c_meta, _ = parse_frontmatter(c_path)
                    client_inn = str(c_meta.get('inn', '')).strip()
                except:
                    pass
            
            invoices.append({
                "path": path,
                "meta": meta,
                "amount": float(meta.get('amount', 0)),
                "inn": client_inn,
                "number": meta.get('invoice_number'),
                "content": content
            })
    return invoices

def mark_invoice_paid(invoice, transaction):
    """Updates the invoice MD file."""
    path = invoice['path']
    print(f"💰 MATCH FOUND! Marking {os.path.basename(path)} as PAID.")
    
    with guard_open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Update Frontmatter using Regex to avoid ruining layout
    # status: Sent -> status: Paid
    # payment_date: ...
    # payment_ref: ...
    
    new_content = content
    
    # Update Status
    if re.search(r'^status:\s*.*$', new_content, re.MULTILINE):
        # Use lowercase 'paid' for Dataview compatibility
        new_content = re.sub(r'^status:\s*.*$', 'status: paid', new_content, flags=re.MULTILINE)
    else:
        # Insert if missing
        new_content = new_content.replace("---\n", "---\nstatus: paid\n", 1)
        
    # Update Tag (unpaid -> paid)
    if 'unpaid_invoice' in new_content:
        new_content = new_content.replace('unpaid_invoice', 'paid_invoice')
    elif 'unpaid' in new_content:
        new_content = new_content.replace('unpaid', 'paid')
        
    payment_updates = {
        'payment_date': transaction.get('documentProcessDate', 'None'),
        'payment_amount': transaction.get('Amount', {}).get('amount', '0.0'),
        'payment_doc': transaction.get('documentNumber', ''),
    }
    
    missing_keys = []
    
    for key, value in payment_updates.items():
        if re.search(fr'^{key}:\s*.*$', new_content, re.MULTILINE):
            new_content = re.sub(fr'^{key}:\s*.*$', f'{key}: {value}', new_content, flags=re.MULTILINE)
        else:
            missing_keys.append(f"{key}: {value}")
            
    if missing_keys:
        payment_meta = "\n".join(missing_keys) + "\n"
        # Insert into Frontmatter (before the closing ---)
        boundaries = [m.start() for m in re.finditer(r'^---', new_content, re.MULTILINE)]
        
        if len(boundaries) >= 2:
            end_fm = boundaries[1]
            new_content = new_content[:end_fm] + payment_meta + new_content[end_fm:]
        else:
             new_content = re.sub(r'\n---', f"\n{payment_meta}---", new_content, count=1)
    
    with guard_open(path, 'w', encoding='utf-8') as f:
        f.write(new_content)

def reconcile():
    api = TochkaAPI()
    
    print("--- 1. Fetching Bank Statement ---")
    transactions = api.get_statement(days=30)
    
    # Filter for Incoming (Credit)
    incoming_txs = [t for t in transactions if t.get('creditDebitIndicator') == 'Credit']
    print(f"Found {len(incoming_txs)} incoming payments.")
    
    print("\n--- 2. Scanning Open Invoices ---")
    open_invoices = get_open_invoices()
    print(f"Found {len(open_invoices)} open invoices.")
    
    print("\n--- 3. Matching ---")
    matched_count = 0
    
    for tx in incoming_txs:
        tx_id = tx.get('transactionId')
        tx_amount = float(tx.get('Amount', {}).get('amount', 0))
        tx_inn = str(tx.get('DebtorParty', {}).get('inn', '')).strip()
        description = tx.get('description', '').upper()
        
        # Check how much of this transaction is already spent
        spent_amount = get_transaction_matched_amount(tx_id)
        available_balance = tx_amount - spent_amount
        
        if available_balance < 1.0:
            continue # Transaction is fully consumed
            
        for inv in open_invoices:
            # We skip invoices that are already marked paid in the DB or we already processed them in this run
            # Actually open_invoices only contains Unpaid invoices, so it's fine.
            if inv.get('paid_in_this_run'):
                continue
                
            inv_amount = float(inv['amount'])
            
            if inv_amount > available_balance + 1.0:
                continue # This transaction doesn't have enough balance to cover the invoice
                
            inv_inn = str(inv['inn']).strip() if inv['inn'] else ""
            inv_num = str(inv['number']).upper().strip()
            inv_num_clean = inv_num.replace("В24-", "").replace("B24-", "").replace("В-", "").strip()
            
            # Match Logic:
            inn_match = (inv_inn and tx_inn and inv_inn == tx_inn)
            desc_match = False
            
            if inv_num and len(inv_num) > 2 and inv_num in description:
                desc_match = True
            elif inv_num_clean and len(inv_num_clean) > 2 and inv_num_clean in description:
                desc_match = True
                
            if inn_match or desc_match:
                print(f"Checking Invoice {inv['number']} ({inv_amount} RUB)...")
                mark_invoice_paid(inv, tx)
                record_match(tx_id, inv['path'], inv_amount)
                inv['paid_in_this_run'] = True
                
                available_balance -= inv_amount
                matched_count += 1
                
                if available_balance < 1.0:
                    break # Move to next transaction
            
    print(f"\n✅ Reconciliation Complete. Matched {matched_count} invoices.")

if __name__ == "__main__":
    reconcile()
