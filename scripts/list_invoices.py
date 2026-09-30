
from sec_guard import guard_requests_get

import os
import requests
import json
from dotenv import load_dotenv

# Load environment variables
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

# Force disable proxy
for key in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY']:
    os.environ.pop(key, None)

TOKEN = os.environ.get("TOCHKA_TOKEN")
CUSTOMER_CODE = os.environ.get("TOCHKA_CUSTOMER_CODE")
API_URL = "https://enter.tochka.com/uapi/invoice/v1.0/bills"

def list_invoices(inn=None):
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/json"
    }
    
    # The API might require customerCode or taxCode
    params = {}
    if inn:
        params["taxCode"] = inn # Business Park INN: 5074069648
    
    # If standard list doesn't work, try with customerCode
    url = f"{API_URL}"
    
    try:
        # Note: Tochka API endpoints often differ. Let's try GET /bills
        response = guard_requests_get(url, headers=headers, params=params, timeout=15)
        if response.status_code == 200:
            data = response.json()
            invoices = data.get('Data', {}).get('Bill', [])
            return invoices
        else:
            print(f"Error: {response.status_code} - {response.text}")
            return []
    except Exception as e:
        print(f"Exception: {e}")
        return []

if __name__ == "__main__":
    import sys
    inn = sys.argv[1] if len(sys.argv) > 1 else "5074069648"
    print(f"Listing invoices for INN: {inn}...")
    invoices = list_invoices(inn)
    if not invoices:
        print("No invoices found or API error.")
    for inv in invoices:
        status = inv.get('status')
        number = inv.get('number')
        amount = inv.get('totalAmount')
        date = inv.get('date')
        print(f"[{status}] No. {number} | {date} | {amount} RUB")
