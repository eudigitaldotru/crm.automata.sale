import os
import re

BASE_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INVOICES_DIR = os.path.join(BASE_PATH, "30_Invoices")
ACTS_DIR = os.path.join(BASE_PATH, "35_Acts")

VALID_INVOICES = {
    "B24-9283",
    "B24-9262",
    "B24-9261",
    "B24-9122",
    "B24-9121",
    "B24-9258",
    "B24-9257",
    "B24-9256",
    "B24-9120",
    "B24-9119",
    "B24-9118",
    "B24-9117",
    "B24-9116-2",
    "B24-9247-134802",
    "B24-9251-134402",
    "B24-9253-134202"
}

VALID_ACTS = {
    "B24-9257",
    "B24-9256",
    "B24-9258",
    "B24-9120",
    "B24-9117",
    "B24-9151-171003"
}

def extract_b24_number(filename):
    # Match exactly between "№" and " от"
    match = re.search(r'№(B24-[^\s]+) от', filename)
    if match:
        return match.group(1)
    
    # Fallback to general if structure is slightly different
    match = re.search(r'(B24-[\w-]+)', filename)
    if match:
        return match.group(1).rstrip('-')
    return None

def cleanup_directory(directory, valid_set, file_type):
    deleted_count = 0
    if not os.path.exists(directory):
        print(f"Directory {directory} not found.")
        return
        
    for fname in os.listdir(directory):
        if not fname.endswith(".md"):
            continue
            
        b24_num = extract_b24_number(fname)
        if not b24_num:
            print(f"⚠️ Could not parse number from {fname}, skipping.")
            continue
            
        if b24_num not in valid_set:
            file_path = os.path.join(directory, fname)
            print(f"🗑️ Deleting {file_type}: {fname}")
            os.remove(file_path)
            deleted_count += 1
            
    print(f"✅ Finished cleaning {file_type}s. Deleted {deleted_count} files.\n")

if __name__ == "__main__":
    print("🧹 Starting cleanup...")
    cleanup_directory(INVOICES_DIR, VALID_INVOICES, "Invoice")
    cleanup_directory(ACTS_DIR, VALID_ACTS, "Act")
