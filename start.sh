#!/usr/bin/env bash
# Automata CRM — запуск: API (:8001) + дашборд (:5173).
# Останов: Ctrl+C (или закрыть терминал) — оба процесса останавливаются.
set -euo pipefail
cd "$(dirname "$0")"

[ -d venv ] || { echo "Сначала ./install.sh"; exit 1; }

./venv/bin/python -m uvicorn api_server:app --app-dir scripts \
  --host 127.0.0.1 --port 8001 &
API_PID=$!
trap 'kill "$API_PID" 2>/dev/null || true' EXIT
echo "→ API:        http://127.0.0.1:8001   (pid $API_PID)"

if command -v npm >/dev/null 2>&1; then
  echo "→ Дашборд:    http://localhost:5173"
  cd dashboard
  [ -d node_modules ] || npm install --no-fund --no-audit --silent
  npx vite --port 5173
else
  echo "npm не найден — дашборд пропущен. API продолжает работать: http://127.0.0.1:8001"
  wait "$API_PID"
fi
