FROM python:3.12-slim

WORKDIR /app

# Системные зависимости для Telethon (cryptg требует сборки)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY gateway.py userbot.py ./

# gateway слушает на 8443 (userbot портов не открывает)
EXPOSE 8443

# По умолчанию запускается gateway. userbot — через command в compose.
CMD ["python", "gateway.py"]
