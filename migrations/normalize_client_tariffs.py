#!/usr/bin/env python3

from sec_guard import guard_open
import os
import glob
import re
import sys
import fcntl
import subprocess
from datetime import datetime

# YAML parsing fallback (simple regex-based parser to avoid installing PyYAML if not needed, 
# but since PyYAML is already available in the env, we'll use it safely)
try:
    import yaml
except ImportError:
    print("⚠️ PyYAML is required. Run: pip install pyyaml")
    sys.exit(1)

LOCK_FILE = "/tmp/automata_migration.lock"

def check_lock():
    lockfile = guard_open(LOCK_FILE, "w")
    try:
        fcntl.flock(lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return lockfile
    except BlockingIOError:
        print("⚠️ Migration is already running, refusing to start again")
        sys.exit(1)

def backup_clients():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = f"backup-clients-{timestamp}.tar.gz"
    print(f"📦 Creating backup: {backup_file}...")
    subprocess.run(["tar", "-czf", backup_file, "10_Clients/"], check=True)
    print("✅ Backup created successfully.")

def normalize_yaml(content, filename):
    if not content.startswith('---'):
        return content, False

    try:
        fm_end = content.index('---', 3)
    except ValueError:
        return content, False
    
    fm_text = content[3:fm_end]
    try:
        fm = yaml.safe_load(fm_text)
    except yaml.YAMLError as e:
        print(f"⚠️ YAML parsing error in {filename}: {e}")
        return content, False

    if not isinstance(fm, dict):
        return content, False

    # Skip if already migrated (has support_type or lifecycle)
    if 'support_type' in fm or 'lifecycle' in fm:
        return content, False

    tariff = str(fm.get('tariff', '')).strip()
    status = str(fm.get('status', '')).strip()
    item = str(fm.get('retainer_item', '')).strip()
    inc_h = fm.get('included_hours')
    
    # 1. Lifecycle
    if tariff == "Окончен" or status in ("archive", "archived"):
        lifecycle = "churned"
    elif tariff == "Переговоры":
        lifecycle = "negotiation"
    elif status == "active":
        lifecycle = "active"
    else:
        lifecycle = "active"
    
    # 2. Support Type
    if tariff == "Разовые работы":
        support_type = "project"
    elif tariff == "Лицензия":
        support_type = "license"
    elif tariff in ("Мониторинг", "Поддержка 2ч", "Поддержка 3ч", "Поддержка 1ч", "Поддержка 9ч") or 'Поддержка' in tariff:
        support_type = "retainer"
    elif lifecycle in ("churned", "negotiation", "prospect"):
        support_type = "none"
    else:
        support_type = "none"

    # 3. Hours Quota & Support Plan
    support_plan = ""
    support_hours_quota = 0
    
    if support_type == "retainer":
        hours = None
        if inc_h is not None and str(inc_h).isdigit():
            hours = int(inc_h)
        elif item and "x " in item:
            match = re.search(r'x\s*(\d+)', item)
            if match:
                hours = int(match.group(1))
        
        if hours is None:
            if "2ч" in tariff: hours = 2
            elif "3ч" in tariff: hours = 3
            elif "9ч" in tariff: hours = 9
            elif "1ч" in tariff: hours = 1
            elif tariff == "Мониторинг": hours = 1  # From User Q1 answer

        if hours is not None:
            support_hours_quota = hours
            if hours == 1: support_plan = "support_1h"
            elif hours == 2: support_plan = "support_2h"
            elif hours == 3: support_plan = "support_3h"
            elif hours == 9: support_plan = "support_9h"
            else: support_plan = f"support_{hours}h"

    # Update dictionary
    fm['lifecycle'] = lifecycle
    fm['support_type'] = support_type
    
    if support_type == "retainer":
        fm['support_plan'] = support_plan
        # Only keep override if they are not standard, but we default to not setting override since all matched standard prices
    elif support_type == "project":
        fm['support_plan'] = ""
    elif support_type == "license":
        fm['support_plan'] = ""
    elif support_type == "none":
        fm['support_plan'] = ""

    # Remove old fields
    for field in ['status', 'tariff', 'monthly_retainer_fee', 'included_hours', 'type', 'retainer_item']:
        if field in fm:
            del fm[field]

    # Re-serialize
    new_fm_text = yaml.dump(fm, allow_unicode=True, default_flow_style=False, sort_keys=False)
    new_content = f"---\n{new_fm_text}---" + content[fm_end+3:]
    return new_content, True

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--execute', action='store_true', help="Actually modify files (default is dry-run)")
    args = parser.parse_args()

    lock = check_lock()
    
    dry_run = not args.execute
    if dry_run:
        print("🔍 RUNNING IN DRY-RUN MODE (No files will be changed)")
        print("To apply changes, run: python3 migrations/normalize_client_tariffs.py --execute\n")
    else:
        print("🚀 RUNNING IN EXECUTE MODE")
        backup_clients()

    clients = glob.glob("10_Clients/*.md")
    migrated_count = 0

    for f in clients:
        with guard_open(f, 'r', encoding='utf-8') as file:
            content = file.read()
        
        new_content, modified = normalize_yaml(content, f)
        
        if modified:
            migrated_count += 1
            if dry_run:
                # Basic diff parsing
                print(f"📝 Would modify: {f}")
                # Optional: print snippet of new yaml
                fm_end = new_content.index('---', 3)
                print(new_content[:fm_end+3])
                print("-" * 40)
            else:
                with guard_open(f, 'w', encoding='utf-8') as file:
                    file.write(new_content)
                print(f"✅ Modified: {f}")

    print(f"\n✨ Total files {'to be ' if dry_run else ''}migrated: {migrated_count} / {len(clients)}")

if __name__ == "__main__":
    main()
