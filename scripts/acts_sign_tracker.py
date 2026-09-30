#!/usr/bin/env python3
"""acts_sign_tracker.py — страж подписи актов в ЭДО Точки.

Боль владельца: акты уходят клиентам, но Евгений забывает зайти в Точку
и поставить свою подпись. Этот скрипт — «назойливый напоминальщик».

Модель данных (frontmatter счёта в 30_Invoices/):
    owner_signed: false        # акт создан/отправлен, но владелец ещё НЕ подписал в Точке
    owner_signed_notified: ''  # дата последнего напоминания (наг не чаще 1/день)
    owner_signed_date: ''      # когда владелец подтвердил подпись

Правила:
    • акт = счёт с непустым act_id ИЛИ act_pdf;
    • НЕТ поля owner_signed → старый акт (до запуска стража 24.09.2026) — считается
      подписанным, молчим (нулевая миграция);
    • owner_signed: false → nag: hub_push раз в день, пока не закроют;
    • закрытие: --signed <B24-XXXX|all> (15-мин цикл вызывает, когда владелец
      пишет «подписал акт …»); новое ожидание: --pending <B24-XXXX>.

Использование:
    python3 scripts/acts_sign_tracker.py --check           # прогон цикла: наг при нужде
    python3 scripts/acts_sign_tracker.py --list            # показать ждущие
    python3 scripts/acts_sign_tracker.py --signed B24-9345 # отметить подписанным
    python3 scripts/acts_sign_tracker.py --signed all
    python3 scripts/acts_sign_tracker.py --pending B24-9345
"""
import re
import sys
import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
INVOICES = BASE / "30_Invoices"
TODAY = datetime.date.today().isoformat()


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


def set_field(text, key, value):
    if re.search(rf"^{key}:.*$", text, flags=re.M):
        return re.sub(rf"^{key}:.*$", f"{key}: {value}", text, count=1, flags=re.M)
    return text.replace("---\n", f"---\n{key}: {value}\n", 1)


def scan():
    """[(path, meta)] — акты в ожидании подписи владельца."""
    out = []
    for p in sorted(INVOICES.glob("*.md")):
        if p.name.startswith("_"):
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        meta = parse_frontmatter(text)
        has_act = (meta.get("act_id") or "").strip(" '\"") or (meta.get("act_pdf") or "").strip(" '\"")
        if not has_act:
            continue
        if "owner_signed" not in meta:      # старый акт — считаем подписанным
            continue
        if meta.get("owner_signed", "").lower() == "false":
            out.append((p, meta))
    return out


def nag(pending):
    sys.path.insert(0, str(BASE / "scripts"))
    from hub_push import send_event
    items = ", ".join(m.get("invoice_number", p.stem)[:16] for p, m in pending)
    send_event(
        "edo_sign",
        f"В Точке ждут подписи {len(pending)} акт(ов): {items}. Зайди в Точку → ЭДО → подписать. "
        f"Когда подпишешь — напиши в чат «подписал акт <№>» или «подписал все акты».",
        severity="warning",
        push={"title": f"✍️ Подпиши акты в Точке ({len(pending)})",
              "body": f"Ждут: {items}. Откликнись «подписал акт <№>» — напоминание снимется.",
              "channel": "default"},
    )


def check():
    pending = scan()
    if not pending:
        print("✅ актов на подпись в Точке нет")
        return
    to_nag = [(p, m) for p, m in pending if m.get("owner_signed_notified", "") != TODAY]
    if to_nag:
        nag(to_nag)
        for p, m in to_nag:
            p.write_text(set_field(p.read_text(encoding="utf-8"), "owner_signed_notified", TODAY),
                         encoding="utf-8")
        print(f"✍️ напоминание отправлено: {len(to_nag)} акт(ов) ждут подписи "
              f"({', '.join(m.get('invoice_number', '?') for _, m in to_nag)})")
    else:
        print(f"⏳ актов ждут подписи: {len(pending)} — сегодня уже напоминали")


def mark(number, value):
    pending = scan() if value == "true" else []
    targets = []
    if number == "all":
        targets = pending if value == "true" else []
        if not targets:
            print("нет актов в ожидании подписи")
            return
    else:
        for p in list(INVOICES.glob(f"*{number}*.md")):
            meta = parse_frontmatter(p.read_text(encoding="utf-8"))
            if meta.get("invoice_number") == number or number in p.stem:
                targets.append((p, meta))
                break
        if not targets:
            print(f"счёт {number} не найден")
            return
    for p, _ in targets:
        text = p.read_text(encoding="utf-8")
        text = set_field(text, "owner_signed", value)
        if value == "true":
            text = set_field(text, "owner_signed_date", TODAY)
        p.write_text(text, encoding="utf-8")
        print(f"{'✅ подписан' if value == 'true' else '📝 ждёт подписи'}: {p.stem[:60]}")


def main():
    if "--check" in sys.argv:
        check()
    elif "--list" in sys.argv:
        pending = scan()
        if not pending:
            print("актов на подпись нет")
        for p, m in pending:
            print(f"  {m.get('invoice_number', '?'):14} {p.stem[:60]} "
                  f"(наг: {m.get('owner_signed_notified') or '—'})")
    elif "--signed" in sys.argv:
        mark(sys.argv[sys.argv.index("--signed") + 1], "true")
    elif "--pending" in sys.argv:
        mark(sys.argv[sys.argv.index("--pending") + 1], "false")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
