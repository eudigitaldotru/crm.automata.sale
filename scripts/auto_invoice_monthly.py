"""
auto_invoice_monthly.py — Массовое выставление счетов за сопровождение.

Пайплайн на каждого клиента (active + support):
  1. Создание .md счёта в 30_Invoices/ (с защитой от дублей по периоду)
  2. Генерация счёта (PDF) через Точка API  (tochka_api.py)
  3. Генерация акта (PDF) через Точка API   (tochka_api.py --act)
  4. Отправка на email через Resend/SMTP    (send_invoice_email.py)
  5. Отправка в Telegram                    (send_invoice_tg.py — MOCK)

Сводный отчёт в конце показывает по каждому клиенту статус каждого шага:
создан/пропущен, email_status + message_id, TG_status, ошибки.

Использование:
    python3 auto_invoice_monthly.py              # полный прогон
    python3 auto_invoice_monthly.py --dry-run    # без отправки, только отчёт
    python3 auto_invoice_monthly.py --skip-tochka  # пропустить генерацию PDF в Точке
"""
from sec_guard import guard_open

import os
import re
import yaml
import json
import datetime
import subprocess
import sys

# --- Config ---
VAULT_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLIENTS_DIR = os.path.join(VAULT_PATH, "10_Clients")
INVOICES_DIR = os.path.join(VAULT_PATH, "30_Invoices")
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
    return {}, content


def get_next_invoice_number():
    max_num = 9254
    regex = re.compile(r'B24-(\d+)')
    try:
        for fname in os.listdir(INVOICES_DIR):
            match = regex.search(fname)
            if match:
                num = int(match.group(1))
                if num > max_num:
                    max_num = num
    except Exception:
        pass
    return f"B24-{max_num + 1}"


def get_ru_month_name():
    months = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
              "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
    return months[datetime.date.today().month - 1]


def get_period():
    """Текущий период («Август 2026») или переопределённый через --period="..."."""
    forced = None
    for arg in sys.argv[1:]:
        if arg.startswith("--period="):
            forced = arg.split("=", 1)[1].strip()
    return forced or f"{get_ru_month_name()} {datetime.date.today().year}"


def run_step(cmd_list, dry_run=False, label=""):
    """Запускает подпроцесс, возвращает (success, output). В dry-run — не запускает."""
    if dry_run:
        return None, "[DRY-RUN пропущено]"
    try:
        r = subprocess.run(cmd_list, capture_output=True, text=True, timeout=120, check=False)
        output = (r.stdout + r.stderr).strip()
        return r.returncode == 0, output
    except subprocess.TimeoutExpired:
        return False, f"[TIMEOUT] {label} превышено 120с"
    except Exception as e:
        return False, f"[ERROR] {label}: {e}"


def extract_result(stdout_text, key, default=None):
    """Пытается достать значение из JSON-вывода send_invoice_tg/email."""
    # send_invoice_tg печатает JSON в последней строке
    for line in reversed((stdout_text or '').splitlines()):
        line = line.strip()
        if line.startswith('{') and line.endswith('}'):
            try:
                data = json.loads(line)
                if key in data:
                    return data[key]
            except json.JSONDecodeError:
                continue
    return default


def parse_email_status_from_output(output):
    """Извлекает email_status и message_id из вывода send_invoice_email.py."""
    status = None
    message_id = None
    for line in (output or '').splitlines():
        if 'Message ID:' in line:
            m = re.search(r'Message ID:\s*(\S+)', line)
            if m:
                message_id = m.group(1).rstrip('.')
                status = 'sent'
        elif 'sent successfully via Resend' in line or 'Email sent successfully' in line:
            status = 'sent'
        elif 'Failed to send email' in line or 'Resend API Error' in line:
            status = 'failed'
        elif 'No email address' in line:
            status = 'no_email'
        elif 'RESEND_API_KEY not found' in line:
            status = 'no_api_key'
        elif 'PDF link not found' in line:
            status = 'no_pdf'
    return status, message_id


def parse_tg_status_from_output(output, returncode):
    """Анализирует вывод send_invoice_tg.py (MOCK-формат {ok, msg_id})."""
    ok = extract_result(output, 'ok')
    if ok is True:
        return 'mock_sent', extract_result(output, 'msg_id')
    if ok is False:
        code = extract_result(output, 'code', 'unknown')
        return f'mock_failed({code})', None
    # Если не JSON — анализируем returncode
    if returncode == 0:
        return 'mock_sent', None
    return f'failed(rc={returncode})', None


def process_client(client_fname, dry_run=False, skip_tochka=False, preview=False):
    """
    Обрабатывает одного клиента. Возвращает dict-отчёт по шагам:
      {client, status, invoice_number, amount, period, skipped_reason,
       tochka_invoice, tochka_act, email: {status, message_id}, tg: {status, msg_id}, errors:[]}
    """
    report = {
        'client': client_fname.replace('.md', ''),
        'status': 'processed',
        'invoice_number': None,
        'amount': None,
        'period': get_period(),
        'skipped_reason': None,
        'tochka_invoice': None,
        'tochka_act': None,
        'email': {'status': None, 'message_id': None},
        'tg': {'status': None, 'msg_id': None},
        'errors': [],
    }

    client_path = os.path.join(CLIENTS_DIR, client_fname)
    meta, _ = parse_frontmatter(client_path)

    tags = meta.get('tags', [])
    if not isinstance(tags, list) or 'active' not in tags or 'support' not in tags:
        report['status'] = 'skipped'
        report['skipped_reason'] = 'не active+support'
        return report

    # Сумма
    monthly_retainer = meta.get('monthly_retainer_fee')
    if monthly_retainer is not None and float(monthly_retainer or 0) > 0:
        amount = float(monthly_retainer)
        retainer_item = meta.get('retainer_item') or f"[[Service_Support]] x 1 @{int(amount)}"
    else:
        rate = float(meta.get('rate', 0) or 0)
        hours = float(meta.get('hours', 0) or 0)
        amount = rate * hours
        retainer_item = meta.get('retainer_item')
        if not retainer_item:
            if hours > 0:
                retainer_item = f"[[Service_Support]] x {int(hours)} @{int(rate)}"
            else:
                retainer_item = f"[[Service_Support]] x 1 @{int(rate)}"

    report['amount'] = amount

    invoice_number = get_next_invoice_number()
    report['invoice_number'] = invoice_number
    period = report['period']
    today_str = datetime.date.today().strftime("%d.%m.%Y")
    today_iso = datetime.date.today().isoformat()
    due_date_str = (datetime.date.today() + datetime.timedelta(days=7)).strftime("%d.%m.%Y")

    # Защита от дублей: если счёт для этого периода уже есть — пропускаем
    try:
        for fname in os.listdir(INVOICES_DIR):
            if report['client'] in fname:
                inv_path = os.path.join(INVOICES_DIR, fname)
                inv_meta, _ = parse_frontmatter(inv_path)
                if inv_meta.get("period") == period:
                    report['status'] = 'skipped'
                    report['skipped_reason'] = f"счёт за '{period}' уже существует"
                    return report
    except Exception:
        pass

    file_name = f"Счёт №{invoice_number} от {today_str} — {report['client']}.md"
    file_path = os.path.join(INVOICES_DIR, file_name)
    items_yaml = f"items:\n  - \"{retainer_item}\""

    md_content = f"""---
created: {today_iso}
tags:
  - unpaid_invoice
client: "[[{report['client']}]]"
invoice_number: {invoice_number}
invoice_date: {today_iso}
amount: {amount}
status: unpaid
payment_date:
payment_method:
period: {period}
{items_yaml}
---

# Счёт №{invoice_number} от {today_str} — {report['client']}

> **Статус:** 🟡 Не оплачен | **Сумма:** {amount} ₽ | **Дата выставления:** {today_str}

---

## 📋 Детали счёта

**Клиент:** [[{report['client']}]]
**Период работ:** {period}
**Дата выставления:** {today_str}
**Срок оплаты:** {due_date_str} (7 дней)
**Сумма:** {amount} ₽

---

## 📝 Работы по счёту

*(Автоматически созданный счёт по тарифу сопровождения)*
- {retainer_item}

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
    if not dry_run:
        with guard_open(file_path, 'w', encoding='utf-8') as f:
            f.write(md_content)

    # --- Шаг 1: Точка API (счёт PDF) ---
    if not skip_tochka:
        ok, out = run_step(
            [sys.executable, os.path.join(SCRIPTS_DIR, "tochka_api.py"), file_path],
            dry_run, "Точка счёт")
        report['tochka_invoice'] = 'ok' if ok else ('failed' if ok is False else 'dry-run')
        if ok is False:
            report['errors'].append(f"Точка счёт: {(out or '')[:120]}")
    else:
        report['tochka_invoice'] = 'skipped(--skip-tochka)'

    # --- Шаг 2: Точка API (акт PDF) ---
    if not skip_tochka:
        ok, out = run_step(
            [sys.executable, os.path.join(SCRIPTS_DIR, "tochka_api.py"), file_path, "--act"],
            dry_run, "Точка акт")
        report['tochka_act'] = 'ok' if ok else ('failed' if ok is False else 'dry-run')
        if ok is False:
            report['errors'].append(f"Точка акт: {(out or '')[:120]}")
    else:
        report['tochka_act'] = 'skipped(--skip-tochka)'

    # --- Шаг 3: Email ---
    if preview:
        # Режим превью: счёт и PDF созданы, но email НЕ отправляется.
        # Ожидает ручной отправки из дашборда (кнопка «Отправить всем» или точечно).
        report['email']['status'] = 'preview'
    else:
        ok, out = run_step(
            [sys.executable, os.path.join(SCRIPTS_DIR, "send_invoice_email.py"), file_path],
            dry_run, "Email")
        if dry_run:
            report['email']['status'] = 'dry-run'
        else:
            estatus, mid = parse_email_status_from_output(out)
            report['email']['status'] = estatus or ('ok' if ok else 'failed')
            report['email']['message_id'] = mid
            if ok is False:
                report['errors'].append(f"Email: {(out or '')[-200:]}")

    # --- Шаг 4: Telegram (MOCK) ---
    if preview:
        report['tg']['status'] = 'preview(пропущено)'
    else:
        ok, out = run_step(
            [sys.executable, os.path.join(SCRIPTS_DIR, "send_invoice_tg.py"), "--invoice", file_path],
            dry_run, "Telegram")
        if dry_run:
            report['tg']['status'] = 'dry-run(mock)'
        else:
            tg_status, tg_mid = parse_tg_status_from_output(out, 0 if ok else 1)
            report['tg']['status'] = tg_status
            report['tg']['msg_id'] = tg_mid

    return report


def render_summary(reports, dry_run, preview=False):
    """Формирует человекочитаемый сводный отчёт."""
    period = get_period()
    if dry_run:
        mode = "DRY-RUN (без отправки)"
    elif preview:
        mode = "ПРЕВЬЮ (счёт+PDF без email)"
    else:
        mode = "ПОЛНЫЙ ПРОГОН"
    lines = []
    lines.append("=" * 72)
    lines.append(f"{'📋 СВОДНЫЙ ОТЧЁТ: Массовое выставление счетов':^72}")
    lines.append(f"{'Период: ' + period + '  |  Режим: ' + mode:^72}")
    lines.append(f"{'Дата: ' + datetime.datetime.now().strftime('%d.%m.%Y %H:%M'):^72}")
    lines.append("=" * 72)
    lines.append("")

    processed = [r for r in reports if r['status'] == 'processed']
    skipped = [r for r in reports if r['status'] == 'skipped']

    # Сводка
    total_amount = sum(r['amount'] for r in processed if r['amount'])
    email_ok = sum(1 for r in processed if r['email']['status'] == 'sent')
    email_fail = sum(1 for r in processed if r['email']['status'] and r['email']['status'] not in ('sent', 'dry-run'))
    tg_mock = sum(1 for r in processed if 'mock' in str(r['tg'].get('status', '')))

    lines.append(f"📊 ИТОГИ:")
    lines.append(f"   Создано счетов:   {len(processed)}")
    lines.append(f"   Пропущено:        {len(skipped)}")
    lines.append(f"   Сумма выставлена: {total_amount:,.0f} ₽".replace(',', ' '))
    lines.append(f"   Email отправлено: {email_ok} ✅  |  ошибок: {email_fail} ❌")
    lines.append(f"   TG (mock):        {tg_mock} (заглушка — реальной отправки нет)")
    lines.append("")

    # Детально по каждому обработанному
    if processed:
        lines.append("─" * 72)
        lines.append("📤 ВЫСТАВЛЕННЫЕ СЧЕТА:")
        lines.append("─" * 72)
        for r in processed:
            lines.append("")
            lines.append(f"  ▸ {r['client']}  ({r['invoice_number']}, {r['amount']:,.0f} ₽)".replace(',', ' '))
            lines.append(f"      Точка счёт/акт: {r['tochka_invoice']} / {r['tochka_act']}")
            estatus = r['email']['status'] or '?'
            emid = r['email']['message_id']
            email_line = f"      Email: {estatus}"
            if emid:
                email_line += f"  (message_id: {emid})"
            lines.append(email_line)
            lines.append(f"      Telegram: {r['tg'].get('status', '?')}  (mock)")
            if r['errors']:
                for e in r['errors']:
                    lines.append(f"      ⚠️  {e}")
        lines.append("")

    # Пропущенные
    if skipped:
        lines.append("─" * 72)
        lines.append("⏭️  ПРОПУЩЕННЫЕ:")
        lines.append("─" * 72)
        for r in skipped:
            lines.append(f"  • {r['client']}: {r['skipped_reason']}")
        lines.append("")

    lines.append("=" * 72)
    return "\n".join(lines)


def main():
    # Аргументы
    dry_run = '--dry-run' in sys.argv
    skip_tochka = '--skip-tochka' in sys.argv
    preview = '--preview' in sys.argv

    period = get_period()
    print(f"\n🚀 Массовое выставление счетов за {period}...")
    if dry_run:
        print("   (режим DRY-RUN — отправка/генерация пропускаются)\n")
    elif preview:
        print("   (режим ПРЕВЬЮ — счёт+PDF создаются, email НЕ отправляется)\n")

    reports = []
    try:
        for fname in sorted(os.listdir(CLIENTS_DIR)):
            if not fname.endswith('.md'):
                continue
            try:
                report = process_client(fname, dry_run=dry_run, skip_tochka=skip_tochka, preview=preview)
                reports.append(report)
                # Краткий вывод по каждому в процессе
                if report['status'] == 'processed':
                    suffix = " (превью)" if preview else ""
                    print(f"  ✓ {report['client']}: {report['invoice_number']} ({report['amount']:,.0f} ₽){suffix}".replace(',', ' '))
                elif report['status'] == 'skipped':
                    print(f"  ⏭️  {report['client']}: {report['skipped_reason']}")
            except Exception as e:
                print(f"  ❌ {fname}: {e}")
                reports.append({
                    'client': fname.replace('.md', ''), 'status': 'error',
                    'errors': [str(e)], 'amount': 0,
                    'email': {'status': None}, 'tg': {'status': None}
                })
    except Exception as e:
        print(f"❌ Критическая ошибка обхода клиентов: {e}")

    # Сводный отчёт
    summary = render_summary(reports, dry_run, preview=preview)
    print("\n" + summary)

    # Сохраняем отчёт в файл для истории
    log_dir = os.path.join(SCRIPTS_DIR, "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"invoice_run_{datetime.date.today().isoformat()}.txt")
    try:
        with guard_open(log_file, 'w', encoding='utf-8') as f:
            f.write(summary)
            f.write("\n\n--- МАШИННО-ЧИТАЕМЫЙ JSON ---\n")
            json.dump(reports, f, ensure_ascii=False, indent=2)
        print(f"📁 Отчёт сохранён: {log_file}")
    except Exception as e:
        print(f"⚠️  Не удалось сохранить отчёт: {e}")

    # Возвращаемый текст для дашборда — summary (api_server.py отдаёт его в UI)
    return summary


if __name__ == "__main__":
    main()
