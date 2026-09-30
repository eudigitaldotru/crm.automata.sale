# TG-Gateway — Telegram Gateway для AUTOMATA-CRM

Разворачивается на **зарубежном VPS** (где Telegram не заблокирован).
Локальная CRM (в РФ, мобильный интернет с белыми списками) забирает
события исходящими HTTPS-запросами на порт 8443/443.

```
        ┌─────────────────────────────┐
        │   Иностранный VPS           │
        │  ┌─────────────┐            │
        │  │ userbot.py  │ → Telegram │  (Telegram тут доступен напрямую)
        │  └──────┬──────┘            │
        │         │ /internal/event   │
        │  ┌──────▼──────┐            │
        │  │ gateway.py  │  :8443     │  (FastAPI + SQLite)
        │  └──────┬──────┘            │
        └─────────┼───────────────────┘
                  │ HTTPS (исходящий от CRM, проходит белые списки)
                  │ GET /events, POST /send
        ┌─────────▼───────────────────┐
        │   Локальная CRM (РФ)        │
        │   scripts/tg_gateway_client │  → складывает в 20_Inbox/
        └─────────────────────────────┘
```

## Состав

| Файл | Назначение |
|---|---|
| `gateway.py` | FastAPI: SQLite-очередь событий + outbox. Эндпоинты `/events`, `/send`, `/health` |
| `userbot.py` | Telethon userbot: слушает входящие → кладёт в gateway; забирает outbox → отправляет |
| `requirements.txt` | fastapi, uvicorn, telethon, cryptg |
| `docker-compose.yml` | Запуск gateway + userbot в контейнерах |
| `Dockerfile` | Образ на python:3.12-slim |

---

## Этап 1. Подготовка VPS (1 раз)

### 1.1. Выбор VPS
Нидерланды / Германия / Финляндия. Провайдеры: **Hetzner, Aeza, Contabo, 4vps**.
Минимум: **2 vCPU / 4 GB RAM / 40 GB SSD**.

### 1.2. Базовая настройка сервера
```bash
# Создать пользователя (не работать под root)
adduser tgw && usermod -aG sudo tgw
su - tgw

# Файрвол — открыть только SSH + порт gateway
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp        # SSH (или ваш нестандартный порт)
sudo ufw allow 8443/tcp      # gateway
sudo ufw enable

# Docker
sudo apt update && sudo apt install -y docker.io docker-compose-plugin
sudo usermod -aG docker tgw   # выйти-войти после
```

### 1.3. Получить Telegram API ключи
1. Зайдите на https://my.telegram.org → **API development tools**
2. Создайте приложение → получите `api_id` и `api_hash`

---

## Этап 2. Развёртывание gateway

### 2.1. Загрузить файлы на VPS
```bash
# С локальной машины:
scp -r tg-gateway/ tgw@VPS_IP:~/
ssh tgw@VPS_IP
cd tg-gateway
```

### 2.2. Настроить `.env`
```bash
cp .env.example .env
nano .env
# Заполнить:
#   TG_API_ID, TG_API_HASH — из my.telegram.org
#   GATEWAY_TOKEN — сгенерировать: openssl rand -hex 32
nano .env
```

### 2.3. Запустить gateway (без userbot пока)
```bash
docker compose up -d gateway
docker compose logs -f gateway
# Должно быть: "Application startup complete"
# Проверка: curl http://localhost:8443/health → {"ok":true,...}
```

---

## Этап 3. Первый запуск userbot (авторизация)

Userbot требует интерактивной авторизации при первом запуске (код из SMS/Telegram).
Поэтому **первый раз запускаем вручную**, не в docker:

```bash
# На VPS, в папке tg-gateway
pip install -r requirements.txt   # или в venv
export $(grep -v '^#' .env | xargs)
python userbot.py
```

Скрипт попросит:
- номер телефона аккаунта-менеджера (вашего личного)
- код из SMS или из самого Telegram
- (если включена 2FA) — облачный пароль

После авторизации создастся `gateway_session.session`. Теперь userbot слушает
входящие и кладёт их в gateway. Проверьте: напишите себе в Telegram — в консоли
должно появиться `📩 [...] ...`.

**Остановите ручной запуск (Ctrl+C)** — сессия сохранена, теперь можно стартовать в docker.

### 3.1. Запуск userbot в docker
```bash
# Перенести .session в папку для docker-volume
mkdir -p sessions
cp gateway_session.session sessions/

docker compose up -d userbot
docker compose logs -f userbot
```

---

## Этап 4. Подключение локальной CRM

На машине с CRM (в РФ) создайте скрипт-поллер `scripts/tg_gateway_client.py`
(см. `tg_gateway_client.example.py` в этой папке). Настройте в `.env`:

```
TG_GATEWAY_URL=https://VPS_IP:8443
TG_GATEWAY_TOKEN=<тот же GATEWAY_TOKEN>
```

Запускайте поллер в фоне (или через `monitoring_daemon.py`):
```bash
python3 scripts/tg_gateway_client.py
```

Он будет опрашивать `/events` и складывать лиды/сообщения в `20_Inbox/` и
создавать тикеты — точно как раньше делал `tg_listener.py`, но без блокировок.

---

## TLS / HTTPS (важно для белых списков)

Мобильные провайдеры с белыми списками пропускают **443/8443 с TLS**.
Голый HTTP на 8443 могут резать.

**Минимум:** self-signed сертификат + обращение по IP (CRM игнорирует проверку).
```bash
openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem -days 365 -nodes -subj "/CN=VPS_IP"
# Запуск gateway через uvicorn с ssl:
uvicorn gateway:app --host 0.0.0.0 --port 8443 --ssl-keyfile key.pem --ssl-certfile cert.pem
```

**Лучше:** домен + Let's Encrypt + nginx reverse-proxy (443 → 8443).

---

## Чего избегать

- ❌ **Коммитить `.session`-файл** — это полный доступ к аккаунту. Он в `.gitignore` проекта.
- ❌ **Запускать userbot с разных IP** — прыжки IP = быстрый бан аккаунта.
- ❌ **Массовая холодная рассылка** — забанят за часы независимо от gateway.
- ❌ **Держать gateway без `GATEWAY_TOKEN`** — кто угодно прочитает ваши сообщения.

## Бэкапы

Ежедневно бэкапьте (на отдельное хранилище, не на этом VPS):
```bash
# SQLite + сессия
tar czf backup-$(date +%F).tar.gz data/gateway.db sessions/gateway_session.session
# Шифрованно (опционально): gpg -c backup-*.tar.gz
```
