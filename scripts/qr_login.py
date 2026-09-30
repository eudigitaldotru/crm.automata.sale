import os
import sys
import asyncio
import qrcode
from dotenv import load_dotenv
from telethon import TelegramClient, errors

BASE_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
dotenv_path = os.path.join(BASE_PATH, ".env")
load_dotenv(dotenv_path)

API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")

session_dir = os.path.dirname(os.path.abspath(__file__))
session_file = os.path.join(session_dir, 'invoice_session')

client = TelegramClient(session_file, int(API_ID), API_HASH)

async def main():
    print("⏳ Подключение к Telegram...")
    await client.connect()
    if await client.is_user_authorized():
        print("✅ Сессия уже авторизована! Вы можете запускать pm2 start crm-tg-listener")
        return

    print("Генерация QR-кода...")
    qr_login = await client.qr_login()
    
    qr = qrcode.QRCode(border=2)
    qr.add_data(qr_login.url)
    qr.make(fit=True)
    
    print("\n--- ДЛЯ ТЕМНОГО ТЕРМИНАЛА ---")
    qr.print_ascii(invert=True)
    
    print("\n--- ДЛЯ СВЕТЛОГО ТЕРМИНАЛА ---")
    qr.print_ascii(invert=False)
    
    print("\n" + "="*50)
    print("📷 Откройте Telegram на телефоне -> Настройки -> Устройства -> Подключить устройство")
    print("Ожидание сканирования (у вас есть 2 минуты)...")
    print("="*50 + "\n")
    
    try:
        await qr_login.wait(timeout=120)
        print("✅ Успешная авторизация! Файл сессии сохранен.")
        print("▶️ Теперь вы можете запустить бота: pm2 start crm-tg-listener")
    except errors.SessionPasswordNeededError:
        print("\n" + "🔒 "*10)
        print("Включена двухэтапная аутентификация (2FA)!")
        password = input("Пожалуйста, введите ваш облачный пароль Telegram: ")
        try:
            await client.sign_in(password=password)
            print("✅ Успешная авторизация! Файл сессии сохранен.")
            print("▶️ Теперь вы можете запустить бота: pm2 start crm-tg-listener")
        except Exception as e:
            print(f"❌ Неверный пароль или ошибка: {e}")
    except Exception as e:
        print(f"❌ Ошибка или время истекло: {e}")

if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    asyncio.run(main())
