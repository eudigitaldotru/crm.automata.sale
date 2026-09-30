
from sec_guard import guard_open
import os
import yaml
import re
import datetime
import shutil

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INBOX_DIR = os.path.join(BASE_DIR, "20_Inbox")
CLIENTS_DIR = os.path.join(BASE_DIR, "10_Clients")

def sanitize_filename(name):
    return re.sub(r'[\\/*?:"<>|]', "", name)

def parse_frontmatter(file_path):
    try:
        with guard_open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        match = re.search(r'^\s*---\n(.*?)\n---', content, re.DOTALL)
        if match:
             return yaml.safe_load(match.group(1)), content[match.end():]
    except Exception as e:
        pass
    return {}, ""

def process_inbox():
    if not os.path.exists(INBOX_DIR):
        print("Inbox directory not found.")
        return

    processed_count = 0
    for filename in os.listdir(INBOX_DIR):
        if not filename.endswith(".md"):
            continue
            
        filepath = os.path.join(INBOX_DIR, filename)
        meta, body = parse_frontmatter(filepath)
        
        # If it's already assigned to a known client, skip it
        client_tag = meta.get("client")
        if client_tag and client_tag != '""' and client_tag != '':
            print(f"Skipping {filename}: Already assigned to {client_tag}")
            continue
            
        sender = meta.get("sender", "Unknown")
        source = meta.get("source", "inbox")
        
        safe_name = sanitize_filename(sender)
        now = datetime.datetime.now()
        date_str = now.strftime("%Y-%m-%d %H:%M:%S")
        
        lead_filename = f"Лид_{safe_name}.md"
        lead_filepath = os.path.join(CLIENTS_DIR, lead_filename)
        
        if os.path.exists(lead_filepath):
            print(f"Lead already exists for {sender}, skipping.")
            continue
            
        frontmatter = f"""---
created: {now.strftime('%Y-%m-%d')}
modified: {now.strftime('%Y-%m-%d')}
tags: [client, lead]
lifecycle: prospect
support_type: none
support_plan: ""
hours_used_current_month: 0
company_name: "{safe_name}"
contact_name: "{safe_name}"
telegram: ""
telegram_id: ""
phone: ""
source: "{source}"
status: "new"
last_contact_at: "{date_str}"
rate: 3000
total_revenue: 0
invoice_amount: 0
---

# {safe_name} (Лид из Inbox)

> **Жизненный цикл:** `= this.lifecycle` | **Тип:** `= this.support_type` | **План:** `= this.support_plan`

## 💬 Исходное сообщение
{body.strip()}
"""
        try:
            with guard_open(lead_filepath, "w", encoding="utf-8") as f:
                f.write(frontmatter)
            print(f"✅ Created NEW lead from inbox: {lead_filename}")
            
            # Move the original inbox item to a processed folder or delete it
            archive_dir = os.path.join(INBOX_DIR, "processed")
            os.makedirs(archive_dir, exist_ok=True)
            shutil.move(filepath, os.path.join(archive_dir, filename))
            processed_count += 1
        except Exception as e:
            print(f"❌ Failed to process {filename}: {e}")
            
    print(f"Done. Processed {processed_count} inbox items into leads.")

if __name__ == "__main__":
    process_inbox()
