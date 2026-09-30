
import os
import requests
import json

# Force disable proxy
for key in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY']:
    os.environ.pop(key, None)

import os

TOCHKA_TOKEN = os.environ.get("TOCHKA_TOKEN")
if not TOCHKA_TOKEN:
    print("Error: TOCHKA_TOKEN is not set.")
    exit(1)

headers = {
    "Authorization": f"Bearer {TOCHKA_TOKEN}",
    "Content-Type": "application/json",
    "Accept": "application/json"
}

# Try standard Open Banking accounts endpoint
url = "https://enter.tochka.com/uapi/open-banking/v1.0/accounts"

print(f"Fetching accounts from: {url}")
try:
    session = requests.Session()
    session.trust_env = False
    response = session.get(url, headers=headers)
    
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.text}")
    
except Exception as e:
    print(f"Error: {e}")
