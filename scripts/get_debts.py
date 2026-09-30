import os, re, yaml
from pathlib import Path

vault_path = Path('/home/adminus/Документы/OdsidianVault-CRM/AUTOMATA-CRM')
invoices_path = vault_path / '30_Invoices'

total_unpaid = 0
unpaid_by_client = {}
unpaid_invoices = []

if invoices_path.exists():
    for f in invoices_path.glob('*.md'):
        with open(f, 'r', encoding='utf-8') as file:
            content = file.read()
            match = re.search(r'^\s*---\n(.*?)\n---', content, re.DOTALL)
            if match:
                try:
                    fm = yaml.safe_load(match.group(1)) or {}
                    if fm.get('status') == 'unpaid':
                        amount = float(fm.get('amount', 0))
                        client = str(fm.get('client', '')).replace('[[', '').replace(']]', '')
                        inv_num = fm.get('invoice_number', 'Unknown')
                        total_unpaid += amount
                        if client not in unpaid_by_client:
                            unpaid_by_client[client] = 0
                        unpaid_by_client[client] += amount
                        unpaid_invoices.append(f"{client} ({inv_num}): {amount} руб.")
                except:
                    pass

print(f"Total Unpaid: {total_unpaid}")
for inv in unpaid_invoices:
    print(inv)
