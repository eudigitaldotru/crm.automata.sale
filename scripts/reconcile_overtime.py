
from sec_guard import guard_open
import os
import re
import yaml
import datetime
import subprocess

# --- Config ---
VAULT_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLIENTS_DIR = os.path.join(VAULT_PATH, "10_Clients")
INVOICES_DIR = os.path.join(VAULT_PATH, "30_Invoices")
DOCUMENTS_DIR = os.path.join(VAULT_PATH, "60_Documents")
SCRIPTS_DIR = os.path.join(VAULT_PATH, "scripts")

def parse_frontmatter(file_path):
    try:
        with guard_open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        match = re.search(r'^\s*---\n(.*?)\n---', content, re.DOTALL)
        if match:
            return yaml.safe_load(match.group(1)), content
    except Exception:
        pass
    return {}, ""

def get_next_invoice_number():
    max_num = 9254
    regex = re.compile(r'B24-(\d+)')
    for fname in os.listdir(INVOICES_DIR):
        match = regex.search(fname)
        if match:
            num = int(match.group(1))
            if num > max_num:
                max_num = num
    return f"B24-{max_num + 1}"

def get_ru_month_name(month_num=None):
    if month_num is None:
        month_num = datetime.date.today().month
    months = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
    return months[month_num - 1]

def run_command(cmd_list):
    print(f"  => Running: {' '.join(cmd_list)}")
    subprocess.run(cmd_list, check=False)

def check_overtime(client_fname):
    client_path = os.path.join(CLIENTS_DIR, client_fname)
    meta, _ = parse_frontmatter(client_path)
    client_name = client_fname.replace('.md', '')
    
    included_hours = float(meta.get('included_hours', 0))
    rate = float(meta.get('rate', 0))
    
    # Scan 30_Tasks/ for completed, unbilled tasks for this client in the current month
    tasks_dir = os.path.join(VAULT_PATH, "30_Tasks")
    today = datetime.date.today()
    current_month_prefix = f"{today.year}-{today.month:02d}"
    
    month_entries = []
    total_hours = 0.0
    
    if os.path.isdir(tasks_dir):
        for fname in sorted(os.listdir(tasks_dir)):
            if not fname.endswith(".md") or fname == "README.md":
                continue
            tf_path = os.path.join(tasks_dir, fname)
            try:
                tf_meta, tf_content = parse_frontmatter(tf_path)
                if tf_meta.get("type") not in ("task", "dev_task"):
                    continue
                
                # Check client
                client_raw = tf_meta.get("client", "")
                if isinstance(client_raw, str):
                    tf_client = client_raw.replace("[[", "").replace("]]", "").strip()
                else:
                    tf_client = ""
                    
                if tf_client != client_name:
                    continue
                    
                # Check status and invoice
                status = str(tf_meta.get("status", "todo")).lower()
                invoice = tf_meta.get("invoice", "")
                
                # Check completion date
                comp_date = str(tf_meta.get("date_completed") or "")
                
                # We bill tasks that are done, have no invoice, and were completed in current month
                if status == "done" and not invoice and comp_date.startswith(current_month_prefix):
                    task_hours = float(tf_meta.get("hours", 0))
                    total_hours += task_hours
                    task_title = fname.replace(".md", "")
                    header_match = re.search(r'^#\s+(.*?)$', tf_content, re.MULTILINE)
                    if header_match:
                        task_title = header_match.group(1).strip()
                    else:
                        task_title = re.sub(r'^\d{4}-\d{2}-\d{2}_', '', task_title).replace('_', ' ')
                        
                    month_entries.append({
                        "date": comp_date,
                        "agent": tf_meta.get("agent", "AI"),
                        "task": task_title,
                        "hours": task_hours,
                        "file_path": tf_path
                    })
            except Exception as e:
                print(f"[{client_name}] Error parsing task {fname}: {e}")

    if not month_entries:
        # print(f"[{client_name}] No entries for {current_month_prefix}")
        return
        
    print(f"\n[{client_name}] Logged: {total_hours}h | Included: {included_hours}h")
    
    if total_hours <= included_hours:
        print(f"  => No overtime billing needed.")
        return
        
    overage_hours = total_hours - included_hours
    amount = overage_hours * rate
    
    period_str = f"{get_ru_month_name(today.month)} {today.year} (Переработка)"
    
    # Check if we already billed overtime for this month
    for fname in os.listdir(INVOICES_DIR):
        if client_name in fname:
            try:
                inv_path = os.path.join(INVOICES_DIR, fname)
                inv_meta, _ = parse_frontmatter(inv_path)
                if inv_meta.get("period") == period_str:
                    print(f"  => ⏭️ Skipped: Overtime invoice for period '{period_str}' already exists.")
                    return
            except Exception:
                pass
    
    print(f"  => Billing {overage_hours}h overtime = {amount} ₽")
    
    # 1. Generate Markdown Report
    report_name = f"Отчет_о_работах_{get_ru_month_name(today.month)}_{today.year}_{client_name}.md"
    report_path = os.path.join(DOCUMENTS_DIR, report_name)
    report_md = f"# Отчет о выполненных работах за {get_ru_month_name(today.month)} {today.year}\n\n**Клиент:** {client_name}\n\n| Дата | Агент | Задача | Часы |\n|---|---|---|---|\n"
    for e in month_entries:
        report_md += f"| {e.get('date')} | {e.get('agent', 'AI')} | {e.get('task', '')} | {e.get('hours', 0)} |\n"
    
    report_md += f"\n**Всего отработано:** {total_hours} ч.\n**Включено в тариф:** {included_hours} ч.\n**Часы к оплате вне тарифа:** {overage_hours} ч."
    
    with guard_open(report_path, 'w', encoding='utf-8') as f:
        f.write(report_md)
        
    print(f"  => Report generated: {report_name}")
    
    # 2. Generate Invoice
    invoice_number = get_next_invoice_number()
    today_str = datetime.date.today().strftime("%d.%m.%Y")
    today_iso = datetime.date.today().isoformat()
    due_date_str = (datetime.date.today() + datetime.timedelta(days=7)).strftime("%d.%m.%Y")
    
    file_name = f"Счёт №{invoice_number} от {today_str} — {client_name}.md"
    file_path = os.path.join(INVOICES_DIR, file_name)
    
    item_title = f"Дополнительные работы вне тарифа за {get_ru_month_name(today.month)} {today.year} ({overage_hours} ч.)"
    items_yaml = f"items:\n  - \"{item_title}\""
    
    md_content = f"""---
created: {today_iso}
tags:
  - unpaid_invoice
client: "[[{client_name}]]"
invoice_number: {invoice_number}
invoice_date: {today_iso}
amount: {amount}
status: unpaid
payment_date: 
payment_method: 
period: {period_str}
{items_yaml}
---

# Счёт №{invoice_number} от {today_str} — {client_name}

> **Статус:** 🟡 Не оплачен | **Сумма:** {amount} ₽ | **Дата выставления:** {today_str}

---

## 📋 Детали счёта

**Клиент:** [[{client_name}]]
**Период работ:** {period_str}
**Дата выставления:** {today_str}
**Срок оплаты:** {due_date_str} (7 дней)
**Сумма:** {amount} ₽

---

## 📝 Работы по счёту
- {item_title}

*[Смотреть детализированный отчет]({report_path})*

---

## 💳 Оплата

**Дата оплаты:** 
**Способ оплаты:** Точка Банк / СБП / Наличные
**Комментарий:** 

---

## 📎 Файлы и Действия

> [!success] Автоматизация
> [🚀 Сгенерировать и Отправить Счёт (Email + Telegram)](obsidian://shell-commands/?vault=AUTOMATA-CRM&execute=generate_and_send_all)

- [ ] Счёт (PDF)
- [ ] Акт выполненных работ
- [ ] Подписанные документы
"""
    with guard_open(file_path, 'w', encoding='utf-8') as f:
        f.write(md_content)
        
    print(f"  => Created MD file: {file_name}")

    # Mark tasks as billed and link to this invoice
    invoice_link = f"[[Счёт №{invoice_number} от {today_str} — {client_name}]]"
    for e in month_entries:
        tf_path = e["file_path"]
        try:
            with guard_open(tf_path, 'r', encoding='utf-8') as tf:
                tf_text = tf.read()
            if "invoice:" in tf_text:
                tf_text = re.sub(r'invoice:.*', f'invoice: "{invoice_link}"', tf_text)
            else:
                tf_text = tf_text.replace("---\n", f"---\ninvoice: \"{invoice_link}\"\n", 1)
            with guard_open(tf_path, 'w', encoding='utf-8') as tf:
                tf.write(tf_text)
            print(f"   🔗 Linked task {e['task']} to invoice {invoice_number}")
        except Exception as err:
            print(f"   ❌ Error linking task {e['task']}: {err}")
    
    # 3. Call APIs
    run_command(["python3", os.path.join(SCRIPTS_DIR, "tochka_api.py"), file_path])
    run_command(["python3", os.path.join(SCRIPTS_DIR, "send_invoice_email.py"), file_path])
    run_command(["python3", os.path.join(SCRIPTS_DIR, "send_invoice_tg.py"), file_path])
    
    print(f"[{client_name}] ✓ Done.")

def main():
    print(f"Starting Overtime Reconciliation for {get_ru_month_name()} {datetime.date.today().year}...")
    for fname in os.listdir(CLIENTS_DIR):
        if fname.endswith(".md"):
            try:
                check_overtime(fname)
            except Exception as e:
                print(f"Error processing {fname}: {e}")
                
    print(f"\nFINISHED Overtime Reconciliation.")
    
    # Update status file
    status_file = os.path.join(SCRIPTS_DIR, ".status_overtime.json")
    try:
        import json
        with guard_open(status_file, 'w', encoding='utf-8') as f:
            json.dump({
                "last_run": datetime.datetime.now().isoformat(),
                "status": "success"
            }, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error saving status: {e}")

if __name__ == "__main__":
    main()
