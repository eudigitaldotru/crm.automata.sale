import os
import sys
from tochka_api import TochkaAPI
from database import init_db, record_expense

def categorize_expense(description):
    desc = description.lower() if description else ""
    
    if any(k in desc for k in ['magnit', 'pyaterochka', 'krasnoe&beloe', 'krasnoe beloe', 'krasnoye', 'lenta', 'auchan', 'okey']):
        return 'Продукты'
    elif any(k in desc for k in ['sushi', 'bistro', 'restaurant', 'kfc', 'mcdonalds', 'burger', 'vkusno']):
        return 'Кафе/Рестораны'
    elif any(k in desc for k in ['azsb', 'rnazs', 'lukoil', 'gazprom', 'azs', 'rosneft', 'tatneft']):
        return 'Транспорт и Авто'
    elif any(k in desc for k in ['timeweb', 'yandex', 'cloud', 'hosting']):
        return 'Сервисы и Услуги'
    elif any(k in desc for k in ['apteka', 'zdorovie', 'clinic']):
        return 'Медицина'
    else:
        return 'Другое'

def sync_expenses():
    init_db()
    api = TochkaAPI()
    
    print("--- Fetching Bank Statement for Personal Expenses ---")
    # Fetch last 30 days to ensure we have a good window
    transactions = api.get_statement(days=30)
    
    # Filter for Outgoing (Debit)
    outgoing_txs = [t for t in transactions if t.get('creditDebitIndicator') == 'Debit']
    print(f"Found {len(outgoing_txs)} outgoing transactions.")
    
    processed_count = 0
    
    for tx in outgoing_txs:
        tx_id = tx.get('transactionId')
        amount = float(tx.get('Amount', {}).get('amount', 0))
        date_str = tx.get('documentProcessDate', tx.get('documentDate', '1970-01-01'))
        desc = tx.get('description', '')
        
        # Skip if amount is <= 0 or missing ID
        if not tx_id or amount <= 0:
            continue
            
        category = categorize_expense(desc)
        record_expense(tx_id, date_str, amount, desc, category)
        processed_count += 1
        
    print(f"✅ Expense Synchronization Complete. Synced {processed_count} expenses to SQLite.")

if __name__ == "__main__":
    sync_expenses()
