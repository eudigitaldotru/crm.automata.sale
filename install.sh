#!/usr/bin/env bash
# Automata CRM — установка. Идемпотентен: можно запускать повторно.
# --no-dashboard — не ставить Node-зависимости дашборда.
set -euo pipefail
cd "$(dirname "$0")"

echo "[1/4] Python-окружение (venv)…"
[ -d venv ] || python3 -m venv venv
./venv/bin/pip install --quiet --upgrade pip
./venv/bin/pip install --quiet -r requirements.txt

echo "[2/4] Каталоги данных (создаются пустыми, в git не попадают)…"
for d in 10_Clients/Contacts 15_Leads 20_Inbox 20_Outbox 25_Chats \
         30_Deals 30_Invoices 30_Tasks 45_Tickets 55_Goals 60_Documents \
         logs dashboard/public/data; do
  mkdir -p "$d"
done

echo "[3/4] Дашборд (Node.js)…"
if [ "${1:-}" = "--no-dashboard" ]; then
  echo "      пропущено (--no-dashboard)"
elif command -v npm >/dev/null 2>&1; then
  ( cd dashboard && [ -d node_modules ] || npm install --no-fund --no-audit --silent )
else
  echo "      npm не найден — дашборд пропущен (engine/скрипты работают без него)"
fi

echo "[4/4] .env…"
[ -f .env ] || cp .env.example .env

cat <<'NEXT'

✓ Установка завершена.

Дальше:
  1) Заполните .env (минимально можно ничего — локальный режим уже работает)
  2) ./start.sh            # API :8001 + дашборд :5173
  3) Создайте первую карточку:
       ./venv/bin/python scripts/create_entity.py client "ООО Ромашка"

NEXT
