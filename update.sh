#!/usr/bin/env bash
# Automata CRM — обновление. Данные (10_Clients и пр.) не трогает никогда.
set -euo pipefail
cd "$(dirname "$0")"

echo "[1/3] git pull…"
PULL_OUT="$(git pull --ff-only 2>&1)" || { echo "$PULL_OUT"; exit 1; }
echo "$PULL_OUT"

echo "[2/3] Зависимости…"
if [ -d venv ]; then
  ./venv/bin/pip install --quiet -r requirements.txt
fi
if [ -d dashboard/node_modules ] && command -v npm >/dev/null 2>&1; then
  ( cd dashboard && npm install --no-fund --no-audit --silent )
fi

echo "[3/3] Проверка миграций…"
if echo "$PULL_OUT" | grep -q "migrations/"; then
  echo "⚠  Обновление затронуло migrations/ — выполните нужные миграции вручную:"
  ls -1 migrations/
else
  echo "      миграций нет — всё актуально"
fi

echo "✓ Готово. Перезапустите ./start.sh, если он был запущен."
