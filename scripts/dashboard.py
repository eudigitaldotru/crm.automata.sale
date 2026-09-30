
from sec_guard import guard_open

import os
import datetime
import json
from tochka_api import TochkaAPI, parse_frontmatter, find_client_file

INVOICES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "30_Invoices")
DASHBOARD_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dashboard.html")

def get_invoices():
    invoices = []
    # Fallback to 50_Invoices if 30 not found
    target_dir = INVOICES_DIR
    if not os.path.exists(target_dir):
         target_dir = INVOICES_DIR.replace("30_Invoices", "50_Invoices")
    
    if os.path.exists(target_dir):
        for fname in os.listdir(target_dir):
            if not fname.endswith(".md"): continue
            
            path = os.path.join(target_dir, fname)
            meta, _ = parse_frontmatter(path)
            
            # Resolve Client INN
            client_inn = "N/A"
            client_name = meta.get('client', 'Unknown').replace('[[', '').replace(']]', '')
            try:
                c_path = find_client_file(meta.get('client'))
                if c_path:
                    c_meta, _ = parse_frontmatter(c_path)
                    client_inn = str(c_meta.get('inn', 'N/A')).strip()
            except:
                pass

            invoices.append({
                "number": meta.get('invoice_number', 'N/A'),
                "date": meta.get('invoice_date', 'N/A'),
                "client": client_name,
                "amount": float(meta.get('amount', 0)),
                "status": meta.get('status', 'Sent'),
                "inn": client_inn,
                "file": fname
            })
    return invoices

def generate_dashboard():
    # Cache Management
    CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "statement_cache.json")
    USE_CACHE = False
    
    if os.path.exists(CACHE_FILE):
        mtime = os.path.getmtime(CACHE_FILE)
        if (datetime.datetime.now().timestamp() - mtime) < 3600: # 1 hour cache
            USE_CACHE = True
            
    if USE_CACHE:
        print("Using cached statement...")
        with guard_open(CACHE_FILE, "r") as f:
            transactions = json.load(f)
    else:
        print("Fetching statement from API...")
        transactions = api.get_statement(days=30)
        with guard_open(CACHE_FILE, "w") as f:
            json.dump(transactions, f)
            
    incoming_txs = [t for t in transactions if t.get('creditDebitIndicator') == 'Credit']
    
    invoices = get_invoices()
    
    # Analysis Logic
    report_items = []
    
    # Track used transactions to find orphans
    used_tx_ids = set()
    
    for inv in invoices:
        status = "WAITING"
        match_details = ""
        payment_purpose = ""
        row_class = "table-warning"
        
        # Try to match transactions (Even if Paid, to define Used IDs)
        candidates = []
        for tx in incoming_txs:
            if tx.get('transactionId') in used_tx_ids: continue
            
            tx_amount = float(tx.get('Amount', {}).get('amount', 0))
            tx_inn = tx.get('DebtorParty', {}).get('inn')
            
            # Check Amount Match
            if abs(tx_amount - inv['amount']) < 1.0:
                candidates.append({
                    "tx": tx,
                    "inn_match": str(inv['inn']) == str(tx_inn),
                    "inn": tx_inn
                })
        
        best_match = None
        if candidates:
            # Prioritize perfect match
            perfect = [c for c in candidates if c['inn_match']]
            if perfect:
                best_match = perfect[0]
            else:
                best_match = candidates[0]

        if inv['status'].lower() == 'paid':
             status = "PAID"
             row_class = "table-success"
             match_details = "Marked as Paid in Obsidian"
             # If we found a perfect match, mark it as used to clear orphans
             if best_match and best_match['inn_match']:
                  used_tx_ids.add(best_match['tx'].get('transactionId'))
                  payment_purpose = best_match['tx'].get('description', '')
        else:
            if best_match:
                if best_match['inn_match']:
                    status = "MATCH FOUND"
                    row_class = "table-info"
                    match_details = f"Found payment from {best_match['inn']} (Perfect)"
                    payment_purpose = best_match['tx'].get('description', '')
                    used_tx_ids.add(best_match['tx'].get('transactionId'))
                else:
                    status = "INN MISMATCH"
                    row_class = "table-danger"
                    match_details = f"Amount matches, but INN differs! (Exp: {inv['inn']}, Got: {best_match['inn']})"
                    payment_purpose = best_match['tx'].get('description', '')
                    used_tx_ids.add(best_match['tx'].get('transactionId'))
            else:
                status = "NO PAYMENT"
                row_class = ""

        report_items.append({
            "inv": inv,
            "status": status,
            "details": match_details,
            "purpose": payment_purpose,
            "class": row_class
        })

    # Find orphan payments (unmatched)
    orphans = []
    
    # INNs to ignore in orphans list (Rewards, Own Funds, etc.)
    IGNORE_INNS = [
        "7810353960", # TimeWeb
        "{{seller_inn}}",  # ваш ИНН (собственные средства)
    ]
    
    for tx in incoming_txs:
        if tx.get('transactionId') not in used_tx_ids:
            # Check if ignored
            payer_inn = tx.get('DebtorParty', {}).get('inn')
            if str(payer_inn) in IGNORE_INNS:
                continue
                
            orphans.append(tx)

    # Generate HTML
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Reconciliation Dashboard</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        <style>
            body {{ padding: 20px; }}
            .status-badge {{ font-weight: bold; }}
            .purpose-col {{ font-size: 0.85em; color: #555; max-width: 300px; }}
        </style>
    </head>
    <body>
        <h1>📊 Reconciliation Dashboard</h1>
        <p>Generated at: {datetime.datetime.now()}</p>
        
        <h2>Invoices ({len(invoices)})</h2>
        <table class="table table-bordered table-hover">
            <thead>
                <tr>
                    <th>Invoice</th>
                    <th>Date</th>
                    <th>Client</th>
                    <th>Amount</th>
                    <th>INN (Exp)</th>
                    <th>Obsidian Status</th>
                    <th>Reconciliation Status</th>
                    <th>Details</th>
                    <th>Payment Purpose</th>
                </tr>
            </thead>
            <tbody>
    """
    
    for item in report_items:
        inv = item['inv']
        html += f"""
            <tr class="{item['class']}">
                <td>{inv['number']}</td>
                <td>{inv['date']}</td>
                <td>{inv['client']}</td>
                <td>{inv['amount']}</td>
                <td>{inv['inn']}</td>
                <td>{inv['status']}</td>
                <td class="status-badge">{item['status']}</td>
                <td>{item['details']}</td>
                <td class="purpose-col">{item['purpose']}</td>
            </tr>
        """
        
    html += """
            </tbody>
        </table>
        
        <h2>❓ Unmatched Payments (Orphans)</h2>
        <table class="table table-striped">
            <thead>
                <tr>
                    <th>Date</th>
                    <th>Amount</th>
                    <th>Payer</th>
                    <th>INN</th>
                    <th>Description</th>
                </tr>
            </thead>
            <tbody>
    """
    
    for tx in orphans:
        html += f"""
            <tr>
                <td>{tx.get('documentProcessDate')}</td>
                <td>{tx.get('Amount', {}).get('amount')}</td>
                <td>{tx.get('DebtorParty', {}).get('name')}</td>
                <td>{tx.get('DebtorParty', {}).get('inn')}</td>
                <td>{tx.get('description')}</td>
            </tr>
        """

    html += """
            </tbody>
        </table>
    </body>
    </html>
    """
    
    with guard_open(DASHBOARD_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    
    print(f"Dashboard generated: {DASHBOARD_FILE}")

if __name__ == "__main__":
    generate_dashboard()
