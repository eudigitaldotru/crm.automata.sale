
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "crm_state.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # Table for tracked transactions
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS matched_transactions (
            transaction_id TEXT,
            invoice_path TEXT,
            amount REAL,
            matched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (transaction_id, invoice_path)
        )
    ''')
    
    # Table for personal expenses
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS personal_expenses (
            transaction_id TEXT PRIMARY KEY,
            date_str TEXT,
            amount REAL,
            description TEXT,
            category TEXT,
            recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def get_transaction_matched_amount(transaction_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT SUM(amount) FROM matched_transactions WHERE transaction_id = ?', (transaction_id,))
    result = cursor.fetchone()[0]
    conn.close()
    return result if result else 0.0

def record_match(transaction_id, invoice_path, amount):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR IGNORE INTO matched_transactions (transaction_id, invoice_path, amount)
        VALUES (?, ?, ?)
    ''', (transaction_id, invoice_path, amount))
    conn.commit()
    conn.close()

def record_expense(transaction_id, date_str, amount, description, category):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO personal_expenses (transaction_id, date_str, amount, description, category)
        VALUES (?, ?, ?, ?, ?)
    ''', (transaction_id, date_str, amount, description, category))
    conn.commit()
    conn.close()

def get_personal_expenses(month_prefix=None):
    """
    Returns all personal expenses. 
    If month_prefix is provided (e.g. '2026-04'), filters by that month.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    if month_prefix:
        cursor.execute('''
            SELECT transaction_id, date_str, amount, description, category
            FROM personal_expenses
            WHERE date_str LIKE ?
            ORDER BY date_str DESC
        ''', (month_prefix + '%',))
    else:
        cursor.execute('''
            SELECT transaction_id, date_str, amount, description, category
            FROM personal_expenses
            ORDER BY date_str DESC
        ''')
        
    rows = cursor.fetchall()
    conn.close()
    
    expenses = []
    for r in rows:
        expenses.append({
            "transaction_id": r[0],
            "date": r[1],
            "amount": r[2],
            "description": r[3],
            "category": r[4]
        })
    return expenses

if __name__ == "__main__":
    init_db()
    print(f"Database initialized at {DB_PATH}")
