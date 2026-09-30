import os, sys
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from send_invoice_email import send_email, parse_frontmatter, extract_pdf_path, find_client_file

INVOICES_DIR = "/home/adminus/Документы/OdsidianVault-CRM/AUTOMATA-CRM/30_Invoices"

urgent_invoices = [
    "Счёт №B24-9297 от 20.03.2026 — Загреб гостиница.md",
    "Счёт №B24-9291 от 25.03.2026 — Загреб гостиница.md",
    "Счёт №B24-0320-Torex от 20.03.2026 — ООО ТД ТОРЭКС.md"
]

def send_formal_reminders():
    print("Отправляем строгие корпоративные напоминания...")
    count = 0
    for fname in urgent_invoices:
        path = os.path.join(INVOICES_DIR, fname)
        if not os.path.exists(path):
            continue
            
        meta, content = parse_frontmatter(path)
        client_link = meta.get("client")
        if not client_link: continue
        
        client_path = find_client_file(client_link)
        if not client_path: continue
        
        c_meta, _ = parse_frontmatter(client_path)
        email = c_meta.get("email")
        if not email: continue
        
        invoice_number = meta.get("invoice_number", "Б/Н")
        amount = meta.get("amount", "0")
        pdf_path = extract_pdf_path(content, is_act=False)
        
        subject = f"Требуется оплата: Просроченная задолженность по счету №{invoice_number}"
        
        body = f"""Здравствуйте.

Служба биллинга Automata CRM уведомляет вас о наличии просроченной задолженности по ранее выставленному счету №{invoice_number} на сумму {amount} руб.

В связи с закрытием финансовой отчетности за март, убедительно просим произвести оплату не позднее завтрашнего дня (01.04.2026) до 14:00. При отсутствии поступлений мы будем вынуждены временно приостановить оказание услуг по технической поддержке и разработке до полного погашения задолженности.

Счет во вложении.
Надеемся на ваше понимание и оперативное решение данного вопроса.

С уважением,
Финансовый отдел Automata CRM"""

        print(f"-> Sending FORMAL reminder to {email} ({client_link}) for {amount} RUB.")
        if pdf_path:
            send_email(email, subject, body, pdf_path, path)
            count += 1
        else:
            print(f"Missing PDF for {fname}")
            
    print(f"Успешно отправлено: {count} писем.")

if __name__ == "__main__":
    send_formal_reminders()
