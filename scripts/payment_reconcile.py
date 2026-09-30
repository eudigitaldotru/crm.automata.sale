#!/usr/bin/env python3
"""payment_reconcile.py — автосверка оплат: выписка Точки ↔ счета 30_Invoices.

Логика: берёт счета со status sent/unpaid, тянет выписку TochkaAPI.get_statement
(days=7) и ищет входящие платежи, где в назначении есть номер счёта (B24-XXXX)
и совпадает сумма. Найденное → status: paid + payment_date (день из выписки).

    python3 scripts/payment_reconcile.py --dry   # показать сопоставления
    python3 scripts/payment_reconcile.py         # применить

Идемпотентен: оплаченные не трогает. Званый в первом прогоне дня (после expiry_notifier).
"""
import re
import sys
import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
INVOICES = BASE / "30_Invoices"


def parse_frontmatter(text):
    m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return {}
    meta = {}
    for line in m.group(1).splitlines():
        mm = re.match(r"^(\w[\w_]*)\s*:\s*(.*)$", line)
        if mm:
            meta[mm.group(1)] = mm.group(2).strip().strip('"')
    return meta


def set_fields(text, updates):
    for k, v in updates.items():
        text = re.sub(rf"^{k}:.*$", f"{k}: {v}", text, count=1, flags=re.M)
    return text


def main():
    dry = "--dry" in sys.argv
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from tochka_api import TochkaAPI

    # 1) открытые счета
    open_invs = []
    for f in sorted(INVOICES.glob("*.md")):
        meta = parse_frontmatter(f.read_text(encoding="utf-8"))
        if meta.get("status") in ("sent", "unpaid") and meta.get("invoice_number"):
            open_invs.append((f, meta))

    if not open_invs:
        print("открытых счетов нет — сверять нечего")
        return

    # 2) выписка (входящие за 7 дней)
    api = TochkaAPI()
    st = api.get_statement(days=7)
    ops = st if isinstance(st, list) else (st.get("operations") or st.get("data") or [])
    incoming = []
    for o in ops:
        amt = o.get("Amount") or o.get("amount")
        if isinstance(amt, dict):
            amt = amt.get("amount")
        if (o.get("creditDebitIndicator") == "Credit" or o.get("creditDebitIndicator") is None) and amt:
            try:
                amt = float(amt)
            except (TypeError, ValueError):
                continue
            if amt > 0:
                desc = str(o.get("description") or "")
                date = str(o.get("documentProcessDate") or "")[:10]
                incoming.append((amt, date, desc))
    print(f"счетов открыто: {len(open_invs)}, входящих в выписке: {len(incoming)}")

    # 3) сопоставление: номер счёта в назначении + сумма
    matched = 0
    for f, meta in open_invs:
        num = meta["invoice_number"]
        try:
            amount = float(meta.get("amount") or 0)
        except ValueError:
            amount = 0
        for amt, date, desc in incoming:
            if num in desc and abs(amt - amount) < 1:
                print(f"{'[DRY] ' if dry else ''}✅ {num} ({meta.get('client','')}) "
                      f"оплачен {date or '(дата н/д)'}: {amt:.0f} ₽ ← «{desc[:60]}»")
                if not dry:
                    t = f.read_text(encoding="utf-8")
                    t = set_fields(t, {"status": "paid",
                                       "payment_date": date or datetime.date.today().isoformat()})
                    f.write_text(t, encoding="utf-8")
                matched += 1
                break
    if not matched:
        print("совпадений нет")


if __name__ == "__main__":
    main()
