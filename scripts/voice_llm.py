"""LLM-мозг голосовой голограммы (уровень «Б» — абстрактные вопросы).

Транспорт: GLM через Anthropic-совместимый эндпоинт https://api.z.ai/api/anthropic
(нативный /api/paas/v4/chat/completions как фолбэк). Ключ — GLM_API_KEY в .env
проекта (создаётся в консоли z.ai / bigmodel; ключи Coding Plan из ~/.zcode
для прямых вызовов НЕ годятся — проверено, 401).

Контекст собирается из data.json + SQLite-ленты: владелец спрашивает
абстрактно — модель отвечает только по фактам CRM, без выдумок и без действий.
"""

import json
import os
import time
import uuid
from pathlib import Path

BASE_DIR = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
API_URL_ANTHROPIC = "https://api.z.ai/api/anthropic/v1/messages"
API_URL_NATIVE = "https://api.z.ai/api/paas/v4/chat/completions"
DEFAULT_MODEL = os.getenv("GLM_MODEL", "glm-4.7")
QUESTION_LIMIT = 400

# Очередь «мозга на подписке»: вопрос пишет api_server, отвечает
# автоматизация ZCode (CronCreate, каждые 2 мин), голограмма опрашивает ответ.
BRAIN_DIR = BASE_DIR / "scripts" / ".voice_brain"
QUESTION_FILE = BRAIN_DIR / "question.json"
ANSWER_FILE = BRAIN_DIR / "answer.json"


def enqueue(question: str) -> dict:
    """Положить вопрос в очередь моста ZCode-автоматизации."""
    BRAIN_DIR.mkdir(exist_ok=True)
    qid = uuid.uuid4().hex[:12]
    QUESTION_FILE.write_text(json.dumps({
        "id": qid,
        "question": question,
        "ts": time.time(),
        "done": False,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"queued": True, "id": qid}


def poll_answer(qid: str) -> dict:
    """Есть ли ответ автоматизации на вопрос qid."""
    try:
        a = json.loads(ANSWER_FILE.read_text(encoding="utf-8"))
        if a.get("id") == qid and a.get("answer"):
            return {"ready": True, "answer": a["answer"]}
    except Exception:
        pass
    return {"ready": False}

SYSTEM_PROMPT = (
    "Ты Джарвис — ИИ-ассистент Евгения (ИП Automata), отвечаешь голосом в CRM. "
    "Правила: отвечай по-русски, кратко — 2-5 предложений, только для голоса. "
    "Опирайся ТОЛЬКО на предоставленный контекст CRM; если данных нет — так и скажи. "
    "Ничего не обещай сделать и не предпринимай действий — ты только консультируешь. "
    "Тон: спокойно, по-деловому, без воды."
)


def _key():
    # .env проекта уже загружен api_server'ом (load_dotenv)
    return (os.getenv("GLM_API_KEY") or "").strip()


def available() -> bool:
    return bool(_key())


def _context(question: str) -> str:
    """Компактный снимок CRM для ответа: KPI, должники, непрочитанное, задачи, акты."""
    parts = []
    try:
        d = json.load(open(BASE_DIR / "dashboard" / "public" / "data" / "data.json",
                           encoding="utf-8"))
        m = d.get("meta") or {}
        parts.append(
            f"KPI: MRR {m.get('mrr')} ₽, выручка за месяц {m.get('revenue_this_month')} ₽, "
            f"дебиторка {m.get('total_debt')} ₽ (просроченных {m.get('overdue_count')}), "
            f"активных клиентов {m.get('active_clients_count')}."
        )
        unpaid = [i for i in (d.get("invoices") or [])
                  if i.get("status") in ("unpaid", "sent")]
        if unpaid:
            top = sorted(unpaid, key=lambda i: -(i.get("amount") or 0))[:6]
            parts.append("Непогашенные счета: " + "; ".join(
                f"{i.get('client')} {i.get('amount')} ₽ ({i.get('number')})" for i in top))
        acts = [i for i in (d.get("invoices") or [])
                if i.get("act_pdf") and i.get("owner_signed") is False]
        if acts:
            parts.append("Акты без подписи владельца в Точке: " + "; ".join(
                f"{i.get('client')} ({i.get('number')})" for i in acts))
    except Exception as e:
        parts.append(f"(data.json недоступен: {e})")

    # непрочитанные в ленте + открытые задачи — быстро, через те же источники API
    try:
        import sqlite3
        db = BASE_DIR / "crm_state.db"
        if db.exists():
            conn = sqlite3.connect(str(db))
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT client, substr(text,1,50) t FROM chat_messages "
                "ORDER BY ts DESC LIMIT 5").fetchall()
            if rows:
                parts.append("Последнее в ленте: " + "; ".join(
                    f"{r['client']}: {r['t']}" for r in rows))
            conn.close()
    except Exception:
        pass

    try:
        import sys
        sys.path.insert(0, str(BASE_DIR / "scripts"))
        from extract_dashboard_data import extract_gitactive_tasks
        tasks = [t for t in extract_gitactive_tasks() if not t.get("done")][:6]
        if tasks:
            parts.append("Открытые задачи: " + "; ".join(
                f"{t['title']}" + (f" ({t['client']})" if t.get("client") else "")
                for t in tasks))
    except Exception:
        pass

    return "Контекст CRM (сейчас):\n" + "\n".join(parts)[:2600]


def ask(question: str) -> str:
    """Ответ LLM на абстрактный вопрос по контексту CRM. Бросает исключение при сбоях."""
    question = " ".join((question or "").split())[:QUESTION_LIMIT]
    if not question:
        raise ValueError("пустой вопрос")
    key = _key()
    if not key:
        raise RuntimeError("GLM_API_KEY не задан в .env — мозг не подключён")

    ctx = _context(question)
    messages = [
        {"role": "user", "content": f"{ctx}\n\nВопрос владельца: {question}"},
    ]

    import requests

    # основной путь: Anthropic-совместимый
    try:
        r = requests.post(API_URL_ANTHROPIC, timeout=45, headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }, json={
            "model": os.getenv("GLM_MODEL", DEFAULT_MODEL),
            "max_tokens": 500,
            "system": SYSTEM_PROMPT,
            "messages": messages,
        })
        if r.ok:
            data = r.json()
            return "".join(b.get("text", "") for b in data.get("content", [])) \
                .strip() or "(пустой ответ модели)"
        # фолбэк на нативный — если 404/400 по схеме
        if r.status_code in (400, 404):
            r2 = requests.post(API_URL_NATIVE, timeout=45, headers={
                "Authorization": f"Bearer {key}",
                "content-type": "application/json",
            }, json={
                "model": os.getenv("GLM_MODEL", DEFAULT_MODEL),
                "max_tokens": 500,
                "messages": [{"role": "system", "content": SYSTEM_PROMPT}] + messages,
            })
            if r2.ok:
                return (r2.json().get("choices") or [{}])[0] \
                    .get("message", {}).get("content", "").strip() or "(пустой ответ)"
        raise RuntimeError(f"LLM {r.status_code}: {r.text[:200]}")
    except requests.RequestException as e:
        raise RuntimeError(f"LLM недоступен: {e}")
