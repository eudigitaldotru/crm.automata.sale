"""
reconcile_payments.py — Сверка оплат по банковской выписке Точки.

Логика:
  Tochka API /bills/{id} НЕ работает (HTTP 501 Not Implemented), поэтому
  статус счёта в банке никогда не становится 'paid'. Но клиенты платят
  переводом по реквизитам — деньги приходят на счёт, а номер счёта
  B24-XXXX фигурирует в назначении платежа.

  Скрипт:
    1. Берёт выписку (get_statement) за N дней.
    2. В каждом поступлении (Credit) regex-извлекает номера B24-XXXX
       из назначения платежа. Покрывает русскую «В» и латинскую «B»,
       любые разделители (№, пробел, «по сч№», «счет»).
    3. Сопоставляет найденные номера с локальными счетами (30_Invoices/)
       по полю invoice_number. Приоритет — точному совпадению полного
       номера (B24-9119-LIC бьётся раньше, чем префикс B24-9119).
    4. Для неоплаченных счетов (unpaid_invoice) обновляет frontmatter:
       тег unpaid_invoice → paid_invoice, status: paid, payment_date,
       payment_amount, payment_doc.

  Режим dry-run (по умолчанию) только показывает, что было бы изменено.
  Флаг --apply применяет изменения к файлам.

Использование:
    python3 reconcile_payments.py              # dry-run, выписка за 35 дней
    python3 reconcile_payments.py --apply      # применить обновления
    python3 reconcile_payments.py --days 60    # больший горизонт выписки
"""
from sec_guard import guard_open

import os
import re
import sys
import glob
import argparse
import datetime
from pathlib import Path

import yaml

# Импорт банковского клиента из соседнего модуля
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
from tochka_api import TochkaAPI

# --- КОНФИГУРАЦИЯ ---
BASE_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_PATH, ".env"))
INVOICES_DIR = os.path.join(BASE_PATH, "30_Invoices")

# Regex номера счёта: B24-XXXX (4+ цифры), возможно с суффиксом (-LIC, -134802).
# Покрывает русскую «В» (U+0412) и латинскую «B» (U+0042) — визуально неразличимы,
# клиенты пишут обе. Граничные проверки отсекают «B24-9119» внутри «B24-91190».
_INVOICE_NUM_RE = re.compile(r'(?:В|B)24-(\d{4,}(?:-[A-Za-z0-9]+)?)')


def extract_invoice_numbers(description: str) -> list[str]:
    """
    Извлекает ВСЕ номера счетов B24-XXXX из назначения платежа.
    Возвращает полные строки 'B24-9321' (с префиксом), без окружающего мусора.
    Один платёж может покрывать несколько счетов
    (пример: «Оплата по счетам №B24-9311 ... №B24-9297 ... №B24-9306»).
    """
    if not description:
        return []
    found = []
    for m in _INVOICE_NUM_RE.finditer(description):
        # Восстанавливаем каноничный префикс 'B24-' (унифицируем русскую В)
        num = 'B24-' + m.group(1)
        # отсечь ложное совпадение: цифры непосредственно до префикса
        # (например "1B24-9321" — маловероятно, но подстрахуемся)
        start = m.start()
        if start > 0 and description[start - 1].isdigit():
            continue
        found.append(num)
    # Уникальные, сохраняя порядок
    seen = set()
    uniq = []
    for n in found:
        if n not in seen:
            seen.add(n)
            uniq.append(n)
    return uniq


def parse_frontmatter(file_path: str) -> tuple[dict, str]:
    """Возвращает (frontmatter dict, полный текст файла)."""
    with guard_open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    m = re.search(r'^\s*---\n(.*?)\n---', content, re.DOTALL)
    if m:
        try:
            meta = yaml.safe_load(m.group(1)) or {}
            return meta, content
        except yaml.YAMLError:
            return {}, content
    return {}, content


def load_local_invoices() -> dict[str, dict]:
    """
    Загружает все локальные счета. Возвращает:
      {invoice_number: {file, meta, content, unpaid (bool)}}
    Если один номер встречается в нескольких файлах (sync-conflict и т.п.),
    берём первый; всё равно оба файла будут показаны в результатах сверки.
    """
    by_number = {}
    for fp in glob.glob(os.path.join(INVOICES_DIR, '*.md')):
        meta, content = parse_frontmatter(fp)
        num = meta.get('invoice_number')
        if not num:
            continue
        num = str(num).strip()
        tags = meta.get('tags', [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(',')]
        # Дашборд определяет «ждёт оплаты» по набору статусов, не по тегу:
        # unpaid / sent / pending / awaiting_payment (счёт, отправленный
        # через Точку, живёт с status: sent — кейс ЭЛМОН B24-9345).
        # Набор синхронен с extract_dashboard_data.py и api_server.py.
        status = str(meta.get('status', '')).strip().lower()
        unpaid = status in ('unpaid', 'sent', 'pending', 'awaiting_payment')
        entry = {
            'file': fp,
            'meta': meta,
            'content': content,
            'unpaid': unpaid,
            'amount': meta.get('amount'),
            'tags': tags,
        }
        # Первый незаплаченный имеет приоритет при сопоставлении;
        # иначе первый встретившийся. Дубли сохраняем в 'dups'.
        if num not in by_number:
            by_number[num] = entry
            by_number[num]['dups'] = []
        else:
            by_number[num].setdefault('dups', []).append(fp)
            # Если текущий — unpaid, а сохранённый — нет, заменим
            if unpaid and not by_number[num]['unpaid']:
                entry['dups'] = by_number[num]['dups']
                by_number[num] = entry
    return by_number


def match_payment_to_invoice(numbers_in_payment: list[str],
                             local_invoices: dict[str, dict]) -> list[str]:
    """
    Сопоставляет номера из платежа с локальными счетами.
    Приоритет: точное совпадение полного номера (включая суффикс) выше,
    чем совпадение по префиксу. Решает конфликт B24-9119 vs B24-9119-LIC:
    если в платеже написано «B24-9119», совпадёт ТОЛЬКО B24-9119, не LIC.
    Возвращает список invoice_number, которые реально есть локально и unpaid.
    """
    local_nums = set(local_invoices.keys())
    matched = []
    for num in numbers_in_payment:
        if num in local_nums:
            matched.append(num)
            continue
        # Если точного нет — возможно, клиент написал только базовую часть
        # (B24-9119), а локально есть B24-9119-LIC. Пробуем найти как префикс.
        prefix_matches = [ln for ln in local_nums if ln.startswith(num + '-')]
        # Берём только если НЕТ локального точного B24-XXXX без суффикса
        # (иначе приписали бы LIC-платёж не туда).
        if prefix_matches and num not in local_nums:
            # если локально есть и короткий, и длинный — это уже покрыто выше;
            # сюда доходим только когда короткого нет → берём длинные
            matched.extend(prefix_matches)
    return list(dict.fromkeys(matched))  # уникальные, порядок сохранён


def update_invoice_frontmatter(entry: dict, payment_date: str,
                                payment_amount: float, payment_doc: str) -> str:
    """
    Обновляет текст файла счёта: тег unpaid→paid, status, payment_*.
    Возвращает новый текст (НЕ записывает на диск — это делает вызывающий).
    """
    content = entry['content']
    new_content = content

    # 1. Тег: меняем unpaid_invoice → paid_invoice, если такой тег есть.
    # Если тега unpaid_invoice нет (статус был unpaid, но теги sent/edo),
    # добавляем paid_invoice в начало списка тегов — не трогая остальные.
    tags = entry.get('tags') or []
    if 'unpaid_invoice' in tags:
        new_content = new_content.replace('- unpaid_invoice', '- paid_invoice')
    elif 'paid_invoice' not in tags:
        # добавим paid_invoice сразу после 'tags:' строки
        new_content = re.sub(r'(^tags:\s*$)',
                             r'\1  - paid_invoice',
                             new_content, count=1, flags=re.MULTILINE)

    # 2. status
    new_content = re.sub(r'^status:\s*unpaid\s*$',
                         'status: paid', new_content, flags=re.MULTILINE)

    # 3. payment_date — заполнить пустое или обновить
    if re.search(r'^payment_date:\s*$', new_content, re.MULTILINE):
        new_content = re.sub(r'^payment_date:\s*$',
                             f'payment_date: {payment_date}',
                             new_content, flags=re.MULTILINE)
    elif not re.search(r'^payment_date:', new_content, re.MULTILINE):
        # поля нет вообще — добавим после status
        new_content = re.sub(r'(^status:.*$)',
                             rf'\1\npayment_date: {payment_date}',
                             new_content, count=1, flags=re.MULTILINE)

    # 4. payment_amount
    if re.search(r'^payment_amount:', new_content, re.MULTILINE):
        new_content = re.sub(r'^payment_amount:.*$',
                             f'payment_amount: {payment_amount}',
                             new_content, flags=re.MULTILINE)
    else:
        new_content = re.sub(r'(^payment_date:.*$)',
                             rf'\1\npayment_amount: {payment_amount}',
                             new_content, count=1, flags=re.MULTILINE)

    # 5. payment_doc (номер платёжного поручения)
    if re.search(r'^payment_doc:', new_content, re.MULTILINE):
        new_content = re.sub(r'^payment_doc:.*$',
                             f'payment_doc: {payment_doc}',
                             new_content, flags=re.MULTILINE)
    else:
        new_content = re.sub(r'(^payment_amount:.*$)',
                             rf'\1\npayment_doc: {payment_doc}',
                             new_content, count=1, flags=re.MULTILINE)

    return new_content


def main():
    ap = argparse.ArgumentParser(description='Сверка оплат по выписке Точки')
    ap.add_argument('--days', type=int, default=35,
                    help='Горизонт выписки в днях (по умолч. 35)')
    ap.add_argument('--apply', action='store_true',
                    help='Применить обновления к файлам (иначе dry-run)')
    args = ap.parse_args()

    print('=' * 70)
    print(f"{'🔍 СВЕРКА ОПЛАТ ПО ВЫПИСКЕ ТОЧКИ':^70}")
    print(f"{'(режим: ' + ('ПРИМЕНЕНИЕ' if args.apply else 'DRY-RUN') + ')':^70}")
    print('=' * 70)

    # 1. Загружаем локальные счета
    local = load_local_invoices()
    unpaid_local = {n: e for n, e in local.items() if e['unpaid']}
    print(f"\n📁 Локально: {len(local)} счетов, из них {len(unpaid_local)} неоплаченных.")

    if not unpaid_local:
        print('✅ Нет неоплаченных счетов — сверки не требуется.')
        return

    # 2. Получаем выписку
    print(f"\n🏦 Запрашиваю выписку за {args.days} дней...")
    api = TochkaAPI()
    txs = api.get_statement(days=args.days)
    credits = [t for t in txs
               if t.get('creditDebitIndicator') == 'Credit'
               and t.get('status') == 'Booked']
    print(f"   Получено {len(txs)} транзакций, из них {len(credits)} поступлений.")

    # 3. Извлекаем номера из назначений и сопоставляем
    print('\n' + '─' * 70)
    print('🔎 Сопоставление:')
    updates = []  # (invoice_number, entry, payment_date, payment_amount, payment_doc)
    unmatched_payments = []  # поступления без распознанного номера

    for t in credits:
        desc = t.get('description') or ''
        amt = t.get('Amount', {}).get('amount', 0)
        date = t.get('documentProcessDate', '')
        doc_num = str(t.get('documentNumber') or '')

        nums = extract_invoice_numbers(desc)
        if not nums:
            unmatched_payments.append((date, amt, desc))
            continue

        matched = match_payment_to_invoice(nums, local)
        if not matched:
            print(f"   ⚠️  {date} | +{amt:>9} | номера {nums} не найдены локально")
            unmatched_payments.append((date, amt, desc))
            continue

        for inv_num in matched:
            entry = local[inv_num]
            # нас интересуют только unpaid; уже оплаченные не трогаем
            if not entry['unpaid']:
                print(f"   ⏭️  {inv_num} уже оплачен — пропуск ({date}, +{amt})")
                continue
            print(f"   ✅ {inv_num:18} ← платёж {date} +{amt:>9} (поручение №{doc_num})")
            if entry.get('dups'):
                print(f"       дубликаты sync-conflict: {len(entry['dups'])} шт — не обновляю")
            updates.append((inv_num, entry, date, amt, doc_num))

    # 4. Сводка по нераспознанным поступлениям
    if unmatched_payments:
        print(f"\n   ℹ️  {len(unmatched_payments)} поступлений без номера счёта в назначении:")
        for date, amt, desc in unmatched_payments:
            short = (desc or '(пусто)')[:80]
            print(f"      {date} | +{amt:>9} | {short}")

    # 5. Применяем (или нет)
    print('\n' + '═' * 70)
    if not updates:
        print('🏁 Нечего обновлять — все платежи уже сопоставлены или нет совпадений.')
        return

    print(f'💳 Будет помечено оплаченным: {len(updates)} счетов.')
    if not args.apply:
        print('   (dry-run — файлы не изменялись. Запустите с --apply для записи.)')
        return

    applied = 0
    for inv_num, entry, pdate, pamt, pdoc in updates:
        new_content = update_invoice_frontmatter(entry, pdate, pamt, pdoc)
        try:
            with guard_open(entry['file'], 'w', encoding='utf-8') as f:
                f.write(new_content)
            print(f"   ✏️  {inv_num}: обновлён {os.path.basename(entry['file'])}")
            applied += 1
        except Exception as e:
            print(f"   ❌ {inv_num}: ошибка записи — {e}")

    print(f"\n🎉 Готово. Обновлено счетов: {applied}/{len(updates)}.")
    print("   Дашборд подтянет изменения после следующего /api/sync-tasks или /api/refresh.")


if __name__ == '__main__':
    main()
