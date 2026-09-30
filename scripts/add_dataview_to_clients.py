
from sec_guard import guard_open
import os

BASE_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLIENTS_DIR = os.path.join(BASE_PATH, "10_Clients")

DATAVIEW_BLOCK = """
## 📄 Счета и Акты

### Счета
```dataview
TABLE status as Статус, amount as Сумма, invoice_date as Дата, payment_date as Оплачен
FROM "30_Invoices"
WHERE client = this.file.link OR contains(client, this.file.name)
SORT invoice_date DESC
```

### Акты
```dataview
TABLE status as Статус, amount as Сумма, invoice_date as Дата
FROM "35_Acts"
WHERE client = this.file.link OR contains(client, this.file.name)
SORT invoice_date DESC
```
"""

def update_clients():
    for fname in os.listdir(CLIENTS_DIR):
        if not fname.endswith(".md"):
            continue
            
        file_path = os.path.join(CLIENTS_DIR, fname)
        with guard_open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
            
        if "## 📄 Счета и Акты" in content:
            # Replace the old block with the new one
            import re
            content = re.sub(r'## 📄 Счета и Акты.*?(?=---|\Z)', DATAVIEW_BLOCK + '\n', content, flags=re.DOTALL)
        elif "## 📝 Текущие работы" in content:
            content = content.replace("## 📝 Текущие работы", DATAVIEW_BLOCK + "\n---\n\n## 📝 Текущие работы")
        else:
            content += "\n" + DATAVIEW_BLOCK
            
        with guard_open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"Updated {fname}.")

if __name__ == "__main__":
    update_clients()
