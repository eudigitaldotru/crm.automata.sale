#!/bin/bash

# Переходим в директорию скрипта
cd "$(dirname "$0")"

echo "[1] Создание виртуального окружения..."
python3 -m venv venv

echo "[2] Установка зависимостей..."
source venv/bin/activate
pip install -r requirements.txt

echo "[3] Настройка Cron для регулярного запуска..."
# Путь к текущему скрипту запуска
SCRIPT_DIR=$(pwd)
CRON_JOB="0 10 * * * cd $SCRIPT_DIR && $SCRIPT_DIR/venv/bin/python $SCRIPT_DIR/lead_agent.py"

# Проверяем, есть ли уже этот cron
if crontab -l 2>/dev/null | grep -q "lead_agent.py"; then
    echo "Cron-задача уже существует!"
else
    # Добавляем новую задачу на запуск каждый день в 10:00 утра
    (crontab -l 2>/dev/null; echo "$CRON_JOB") | crontab -
    echo "Cron-задача добавлена (запуск ежедневно в 10:00)."
fi

echo ""
echo "Установка завершена!"
echo "Вы можете запустить парсер вручную прямо сейчас командой:"
echo "./venv/bin/python lead_agent.py"
