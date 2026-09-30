
from sec_guard import guard_requests_get
import os
import requests
import datetime
from monitoring_core import sync_domains_with_monitoring, save_monitoring_data

# Google PageSpeed API allows requests without API key for low volume.
# If rate limited, you will need to add a key.
PAGESPEED_API_URL = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"

def get_pagespeed_score(url, strategy="mobile"):
    params = {
        "url": url,
        "strategy": strategy,
        "category": "performance"
    }
    try:
        resp = guard_requests_get(PAGESPEED_API_URL, params=params, timeout=60)
        if resp.status_code == 200:
            data = resp.json()
            score = data.get("lighthouseResult", {}).get("categories", {}).get("performance", {}).get("score")
            if score is not None:
                return int(score * 100)
        else:
            print(f"API Error ({resp.status_code}): {resp.text}")
    except Exception as e:
        print(f"Request error for {url} ({strategy}): {e}")
    return None

def check_pagespeed():
    data = sync_domains_with_monitoring()
    
    for item in data:
        url = item['url']
        domain = item['domain']
        
        # We only run PageSpeed if the site is up
        if item.get("status") == "down":
            print(f"Skipping PageSpeed for {domain} (Site is down)")
            continue
            
        print(f"Checking PageSpeed for {domain} (Mobile)...")
        mobile_score = get_pagespeed_score(url, "mobile")
        
        print(f"Checking PageSpeed for {domain} (Desktop)...")
        desktop_score = get_pagespeed_score(url, "desktop")
        
        if mobile_score is not None or desktop_score is not None:
            if "pageSpeed" not in item or not isinstance(item["pageSpeed"], dict):
                item["pageSpeed"] = {}
                
            if mobile_score is not None:
                item["pageSpeed"]["mobile"] = mobile_score
            if desktop_score is not None:
                item["pageSpeed"]["desktop"] = desktop_score
                
        item['lastChecked'] = datetime.datetime.utcnow().isoformat() + "Z"

    save_monitoring_data(data)
    print("PageSpeed check complete.")

if __name__ == "__main__":
    check_pagespeed()
