import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "crm_state.db")

def migrate_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print("Starting migration...")
    
    # Check if table exists
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='matched_transactions'")
    if not cursor.fetchone():
        print("Table does not exist. Nothing to migrate.")
        return
        
    # Rename old table
    cursor.execute("ALTER TABLE matched_transactions RENAME TO matched_transactions_old")
    
    # Create new table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS matched_transactions (
            transaction_id TEXT,
            invoice_path TEXT,
            amount REAL,
            matched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (transaction_id, invoice_path)
        )
    ''')
    
    # Copy data
    cursor.execute('''
        INSERT INTO matched_transactions (transaction_id, invoice_path, amount, matched_at)
        SELECT transaction_id, invoice_path, amount, matched_at FROM matched_transactions_old
    ''')
    
    # Drop old table
    cursor.execute("DROP TABLE matched_transactions_old")
    
    conn.commit()
    conn.close()
    print("Migration complete!")

if __name__ == "__main__":
    migrate_db()
