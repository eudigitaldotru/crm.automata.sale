
from sec_guard import guard_open
import os
import json
from datetime import datetime
import yaml

BASE_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLIENTS_DIR = os.path.join(BASE_PATH, "10_Clients")
MONITORING_JSON = os.path.join(BASE_PATH, "dashboard", "public", "data", "monitoring.json")

def load_domains_from_clients():
    """
    Scans 10_Clients for YAML frontmatter and extracts domains.
    Returns a dict: { "domain.com": { "client": "Client Name", "url": "https://domain.com" } }
    """
    domains_dict = {}
    if not os.path.exists(CLIENTS_DIR):
        return domains_dict

    for fname in os.listdir(CLIENTS_DIR):
        if not fname.endswith(".md"): continue
        file_path = os.path.join(CLIENTS_DIR, fname)
        client_name = fname.replace(".md", "")
        
        try:
            with guard_open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            import re
            match = re.search(r'^\s*---\n(.*?)\n---', content, re.DOTALL)
            if match:
                 meta = yaml.safe_load(match.group(1))
                 if meta:
                     tags = meta.get('tags', [])
                     if isinstance(tags, list) and 'archive' in tags:
                         continue
                 if meta and 'domains' in meta and isinstance(meta['domains'], list):
                     for d in meta['domains']:
                         if not d: continue
                         clean_domain = str(d).replace('https://', '').replace('http://', '').split('/')[0].strip()
                         if clean_domain:
                             domains_dict[clean_domain] = {
                                 "client": client_name,
                                 "url": f"https://{clean_domain}",
                                 "domain": clean_domain
                             }
        except Exception as e:
            print(f"Error parsing {fname}: {e}")
            
    return domains_dict

def load_monitoring_data():
    if os.path.exists(MONITORING_JSON):
        try:
            with guard_open(MONITORING_JSON, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return []

def save_monitoring_data(data_list):
    os.makedirs(os.path.dirname(MONITORING_JSON), exist_ok=True)
    with guard_open(MONITORING_JSON, 'w', encoding='utf-8') as f:
        json.dump(data_list, f, ensure_ascii=False, indent=2)

def sync_domains_with_monitoring():
    """
    Merges existing monitoring data with actual domains from CRM.
    Returns the synchronized list of dicts.
    """
    actual_domains = load_domains_from_clients()
    existing_data = load_monitoring_data()
    
    # Map existing data by domain
    existing_map = {item["domain"]: item for item in existing_data if "domain" in item}
    
    synced_list = []
    for dom, info in actual_domains.items():
        if dom in existing_map:
            # Update basic info but keep monitoring state
            entry = existing_map[dom]
            entry["name"] = info["client"]
            entry["url"] = info["url"]
            if "domainExpiryDate" not in entry:
                entry["domainExpiryDate"] = "Unknown"
            if "exposedFiles" not in entry:
                entry["exposedFiles"] = []
            synced_list.append(entry)
        else:
            # New domain
            synced_list.append({
                "name": info["client"],
                "url": info["url"],
                "domain": info["domain"],
                "status": "unknown",
                "expiryDate": "Unknown",
                "domainExpiryDate": "Unknown",
                "exposedFiles": [],
                "pageSpeed": None,
                "lastChecked": datetime.utcnow().isoformat() + "Z"
            })
            
    # Note: we intentionally drop domains that are no longer in CRM
    return synced_list

def update_monitoring_field(domain, field, value):
    data = sync_domains_with_monitoring()
    for item in data:
        if item["domain"] == domain:
            item[field] = value
            item["lastChecked"] = datetime.utcnow().isoformat() + "Z"
    save_monitoring_data(data)
