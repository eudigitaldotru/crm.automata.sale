import os
import subprocess
import yaml
import re

INVOICES_DIR = "30_Invoices"
SCRIPTS_DIR = "scripts"

errors = []
sent_count = 0
for fname in os.listdir(INVOICES_DIR):
    if fname.endswith(".md") and ("31.03.2026" in fname or "01.04.2026" in fname):
        fpath = os.path.join(INVOICES_DIR, fname)
        
        with open(fpath, 'r', encoding='utf-8') as f:
            content = f.read()
        match = re.search(r'^\s*---\n(.*?)\n---', content, re.DOTALL)
        if not match: continue
        meta = yaml.safe_load(match.group(1)) or {}
        
        tags = meta.get('tags', [])
        if isinstance(tags, str): tags = [tags]
        if "canceled" in tags:
            continue
        
        print(f"Processing {fname}...")
        
        res1 = subprocess.run(["python3", os.path.join(SCRIPTS_DIR, "send_invoice_tg.py"), fpath], capture_output=True, text=True)
        if res1.returncode != 0:
            print(f"❌ ERROR (Invoice) {fname}: {res1.stdout}\n{res1.stderr}")
            errors.append(fname)
            continue
        else:
            sent_count += 1
            
        res2 = subprocess.run(["python3", os.path.join(SCRIPTS_DIR, "send_invoice_tg.py"), fpath, "--act"], capture_output=True, text=True)
        if res2.returncode != 0:
            if "PDF link not found" in res2.stdout + res2.stderr:
                print(f"⚠️ Warning (Act) {fname}: No Act PDF found.")
            else:
                print(f"❌ ERROR (Act) {fname}: {res2.stdout}\n{res2.stderr}")
                errors.append(fname)
        else:
            sent_count += 1

print(f"\nFinished. Successfully sent {sent_count} documents.")
if errors:
    print(f"Failures: {len(errors)}")
