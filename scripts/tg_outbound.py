"""
tg_outbound.py — Отправка сообщений в Telegram через VPS-gateway.

Локальная CRM (в РФ) отправляет исходящие через POST /send на gateway.
Gateway кладёт в outbox → userbot на VPS доставляет в Telegram.

Важно: отправка только клиентам с已有 chat_id (из входящих сообщений).
Userbot НЕ пишет первым — это вызовет бан аккаунта.
"""
from sec_guard import guard_urlopen

import os
import re
import json
import uuid
import urllib.request
import ssl
from pathlib import Path

from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent.parent
load_dotenv(BASE / ".env")

GATEWAY_URL = os.getenv("TG_GATEWAY_URL", "").rstrip("/")
GATEWAY_TOKEN = os.getenv("TG_GATEWAY_TOKEN", "")
INBOX_DIR = BASE / "20_Inbox"
CLIENTS_DIR = BASE / "10_Clients"

_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE


def resolve_chat_id(client_name: str) -> str:
    """
    Находит идентификатор клиента для отправки в Telegram.

    Userbot на VPS через Telethon get_entity() может резолвить:
      - числовой chat_id (точнее всего)
      - @username (если пользователь публичный)
      - телефон +7XXXXXXXXXX (если контакт есть в диалогах аккаунта)

    Источники (по приоритету):
      1. tg_id/chat_id в карточке клиента (числовой)
      2. tg_id/chat_id в 20_Inbox/ (числовой, из входящих)
      3. tg_id в 15_Leads/ (числовой)
      4. telegram/phone в карточке клиента (телефон или @username — fallback)

    Возвращает идентификатор как строку, или None если данных нет.
    """
    import yaml

    def _try_extract_numeric(meta):
        """Извлекает числовой id из полей tg_id или chat_id."""
        for field in ("tg_id", "chat_id"):
            val = str(meta.get(field) or "").strip().strip('"').strip("'")
            if val and val.lstrip("-").isdigit():
                return val
        return None

    def _try_extract_any(meta):
        """Извлекает ЛЮБОЙ идентификатор (число, @username, телефон)."""
        # Сначала числовой
        num = _try_extract_numeric(meta)
        if num:
            return num
        # Потом telegram/@username/телефон
        for field in ("telegram", "tg_username"):
            val = str(meta.get(field) or "").strip().strip('"').strip("'")
            if val:
                return val
        return None

    # 1. Числовой tg_id в карточке клиента
    client_path = CLIENTS_DIR / f"{client_name}.md"
    if client_path.exists():
        try:
            content = client_path.read_text(encoding="utf-8")
            m = re.search(r"^\s*---\n(.*?)\n---", content, re.DOTALL)
            if m:
                meta = yaml.safe_load(m.group(1)) or {}
                result = _try_extract_numeric(meta)
                if result:
                    return result
        except Exception:
            pass

    # 2-3. Числовой id в Inbox и Leads
    search_dirs = [INBOX_DIR, BASE / "15_Leads"]
    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        for f in search_dir.glob("*.md"):
            try:
                content = f.read_text(encoding="utf-8")
                matched = (client_name in content or
                          f"[[" + client_name + "]]" in content or
                          (search_dir.name == "15_Leads" and client_name in f.stem))
                if not matched:
                    continue
                m = re.search(r"^\s*---\n(.*?)\n---", content, re.DOTALL)
                if m:
                    meta = yaml.safe_load(m.group(1)) or {}
                    result = _try_extract_numeric(meta)
                    if result:
                        return result
            except Exception:
                continue

    # 4. Fallback: telegram/phone из карточки клиента (userbot резолвит через get_entity)
    if client_path.exists():
        try:
            content = client_path.read_text(encoding="utf-8")
            m = re.search(r"^\s*---\n(.*?)\n---", content, re.DOTALL)
            if m:
                meta = yaml.safe_load(m.group(1)) or {}
                result = _try_extract_any(meta)
                if result:
                    return result
        except Exception:
            pass

    return None


def send_via_gateway(chat_id: str, text: str, idempotency_key: str = None,
                     pdf_base64: str = None, pdf_filename: str = None) -> dict:
    """
    Отправляет сообщение в Telegram через VPS-gateway.
    Если передан pdf_base64 — PDF будет отправлен как вложение (текст → caption).
    Возвращает dict: {ok, outbox_id, status} или {ok: false, error}.
    """
    if not GATEWAY_URL:
        return {"ok": False, "error": "TG_GATEWAY_URL не настроен"}
    if not chat_id:
        return {"ok": False, "error": "Пустой chat_id"}

    if idempotency_key is None:
        idempotency_key = f"crm-tg-{uuid.uuid4().hex[:12]}"

    body = {
        "idempotency_key": idempotency_key,
        "channel_id": 1,
        "chat_id": str(chat_id),
        "text": text or "",
    }
    if pdf_base64:
        body["pdf_base64"] = pdf_base64
        body["pdf_filename"] = pdf_filename or "document.pdf"

    payload = json.dumps(body).encode("utf-8")

    url = f"{GATEWAY_URL}/send"
    req = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("Content-Type", "application/json")
    if GATEWAY_TOKEN:
        req.add_header("Authorization", f"Bearer {GATEWAY_TOKEN}")

    try:
        with guard_urlopen(req, timeout=15, context=_SSL_CTX) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return {"ok": True, "outbox_id": data.get("outbox_id"),
                    "status": data.get("status"), "deduplicated": data.get("deduplicated", False)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def send_invoice_to_telegram(client_name: str, tg_text: str, invoice_number: str = "",
                             invoice_pdf_path: str = None) -> dict:
    """
    Полный flow: находит chat_id клиента → отправляет TG через gateway (с PDF-вложением).
    Возвращает {ok, chat_id, outbox_id} или {ok: false, reason}.
    """
    chat_id = resolve_chat_id(client_name)
    if not chat_id:
        return {"ok": False, "reason": "no_chat_id",
                "message": f"У клиента «{client_name}» нет активного диалога в Telegram"}

    # Читаем PDF и кодируем в base64 (если файл есть)
    pdf_base64 = None
    pdf_filename = None
    if invoice_pdf_path:
        pdf_full = Path(invoice_pdf_path)
        if not pdf_full.is_absolute():
            pdf_full = BASE / "60_Documents" / invoice_pdf_path
        if pdf_full.exists():
            import base64
            pdf_base64 = base64.b64encode(pdf_full.read_bytes()).decode("utf-8")
            pdf_filename = pdf_full.name
        else:
            print(f"⚠️ PDF не найден: {pdf_full}")

    # Уникальный ключ при каждом вызове
    import time as _time
    idem_key = f"inv-{invoice_number}-tg-{int(_time.time())}" if invoice_number else None
    result = send_via_gateway(chat_id, tg_text, idempotency_key=idem_key,
                              pdf_base64=pdf_base64, pdf_filename=pdf_filename)
    result["chat_id"] = chat_id
    result["pdf_attached"] = pdf_base64 is not None
    return result
