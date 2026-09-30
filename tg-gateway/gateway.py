"""
gateway.py — Telegram Gateway API для AUTOMATA-CRM.

Развёртывается на зарубежном VPS (где Telegram не заблокирован).
Принимает события от userbot.py (локально на VPS) и отдаёт их
локальной CRM (в РФ, мобильный интернет с белыми списками).

Принципы:
  - CRM делает только ИСХОДЯЩИЕ запросы (GET /events, POST /send)
    → проходит белые списки провайдера (порт 443/8443).
  - Входящих соединений от CRM не требуется (нет вебхуков).
  - События персистентны в SQLite — CRM может упасть/отключиться,
    ничего не теряется, при reconnect курсор (after=) продолжит с места.

Эндпоинты (слушают на 0.0.0.0, ставьте за nginx/reverse-proxy с TLS):
  GET  /events?after=<seq>&limit=<n>&wait=<sec>   — забор событий (long-poll)
  POST /events/ack                                 — CRM подтвердила забор: удалить события ≤ seq
                                                    (зарубежная БД = транзитный буфер, не хранилище)
  POST /send                                       — отправить сообщение в Telegram
  GET  /health                                     — healthcheck
  POST /internal/event                             — userbot кладёт сюда событие

152-ФЗ: персональные данные (тексты, телефоны, username) не должны накапливаться
в БД за пределами РФ. Поэтому: события удаляются по подтверждению CRM (/events/ack)
и самоходной чисткой старше GATEWAY_RETENTION_DAYS (по умолчанию 7 дней).
Хранение и обработка ведутся в CRM на территории РФ.
"""
import os
import json
import time
import sqlite3
import asyncio
import threading
import datetime
from contextlib import contextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# --- КОНФИГУРАЦИЯ ---
DB_PATH = os.getenv("GATEWAY_DB", "gateway.db")
# Токен для авторизации CRM и userbot. Обязателен.
GATEWAY_TOKEN = os.getenv("GATEWAY_TOKEN", "")
# Список токенов через запятую (если несколько клиентов): GATEWAY_TOKENS=a,b,c
GATEWAY_TOKENS = {t.strip() for t in os.getenv("GATEWAY_TOKENS", "").split(",") if t.strip()}
VALID_TOKENS = ({GATEWAY_TOKEN} | GATEWAY_TOKENS) if (GATEWAY_TOKEN or GATEWAY_TOKENS) else set()

# Long-poll: сколько секунд держать соединение, если новых событий нет
LONGPOLL_MAX_WAIT = int(os.getenv("LONGPOLL_MAX_WAIT", "30"))

# Сколько дней максимум событие может лежать в БД шлюза без подтверждения CRM.
# Самоходная чистка (см. _maintenance_worker) — страховка от накопления ПДн.
RETENTION_DAYS = int(os.getenv("GATEWAY_RETENTION_DAYS", "7"))

app = FastAPI(title="AUTOMATA TG Gateway", version="1.0.0")

# ---------------------------------------------------------------------------
# БД: SQLite (одно подключение на поток + таймаут, WAL для конкурентности)
# ---------------------------------------------------------------------------

_lock = threading.Lock()


def init_db():
    with get_db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS events (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER,
            dedup_key TEXT UNIQUE,
            chat_id TEXT,
            kind TEXT,                 -- 'message' | 'status' | 'media'
            payload TEXT NOT NULL,     -- JSON
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_events_seq ON events(seq);

        CREATE TABLE IF NOT EXISTS outbox (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            idempotency_key TEXT UNIQUE NOT NULL,
            channel_id INTEGER,
            chat_id TEXT,
            text TEXT,
            reply_to INTEGER,
            status TEXT DEFAULT 'pending',  -- pending | sent | failed
            tg_message_id INTEGER,
            attempts INTEGER DEFAULT 0,
            error TEXT,
            pdf_base64 TEXT,                 -- PDF-вложение (base64), NULL если нет
            pdf_filename TEXT,               -- имя файла для вложения
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_outbox_status ON outbox(status);

        CREATE TABLE IF NOT EXISTS userbot_heartbeat (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            last_ping TEXT,
            me_id TEXT,
            me_name TEXT
        );
        """)


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    try:
        yield conn
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Авторизация
# ---------------------------------------------------------------------------
def check_auth(request: Request):
    if not VALID_TOKENS:
        return  # токены не настроены — режим без авторизации (только для локальной отладки!)
    auth = request.headers.get("authorization", "")
    token = auth.replace("Bearer ", "").strip() if auth.startswith("Bearer ") else ""
    if token not in VALID_TOKENS:
        raise HTTPException(status_code=401, detail="invalid token")


# ---------------------------------------------------------------------------
# Модели
# ---------------------------------------------------------------------------
class EventIn(BaseModel):
    channel_id: Optional[int] = 1
    dedup_key: str
    chat_id: str
    kind: str = "message"
    payload: dict


class SendRequest(BaseModel):
    idempotency_key: str
    channel_id: int = 1
    chat_id: str
    text: str
    reply_to: Optional[int] = None
    pdf_base64: Optional[str] = None      # PDF во вложении (base64-encoded)
    pdf_filename: Optional[str] = None     # Имя файла (например "Invoice_B24-9333.pdf")
    author: Optional[str] = "evgeny"       # кто автор текста: evgeny | jarvis (для ленты CRM)


class AckIn(BaseModel):
    last_seq: int


# ---------------------------------------------------------------------------
# Long-poll: ожидалка новых событий
# ---------------------------------------------------------------------------
# Глобальный «будильник»: когда userbot кладёт новое событие, будит ждущих.
_new_event = asyncio.Event()


def _notify_new_event():
    """Вызывается из sync-контекста (userbot) при добавлении события."""
    # Планируем set в event-loop FastAPI
    try:
        loop = asyncio.get_event_loop()
        loop.call_soon_threadsafe(_new_event.set)
    except RuntimeError:
        pass


@app.on_event("startup")
async def _startup():
    init_db()
    # Чистка старых событий (152-ФЗ: буфер, а не хранилище)
    asyncio.create_task(_maintenance_worker())


# ---------------------------------------------------------------------------
# Эндпоинты
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    """Healthcheck: статус gateway + userbot (по свежести heartbeat)."""
    with get_db() as conn:
        n_events = conn.execute("SELECT COUNT(*) AS c FROM events").fetchone()["c"]
        n_pending = conn.execute("SELECT COUNT(*) AS c FROM outbox WHERE status='pending'").fetchone()["c"]
        last_seq = conn.execute("SELECT MAX(seq) AS s FROM events").fetchone()["s"] or 0
        hb = conn.execute("SELECT last_ping, me_id, me_name FROM userbot_heartbeat WHERE id=1").fetchone()
    # userbot жив, если heartbeat был за последние 90 сек (userbot пингает каждые 30с)
    userbot_alive = False
    userbot_me = None
    if hb and hb["last_ping"]:
        userbot_me = {"id": hb["me_id"], "name": hb["me_name"]}
        try:
            last = datetime.datetime.fromisoformat(hb["last_ping"])
            userbot_alive = (datetime.datetime.now() - last).total_seconds() < 90
        except Exception:
            pass
    return {
        "ok": True,
        "events": n_events,
        "pending_outbox": n_pending,
        "last_seq": last_seq,
        "userbot": {"alive": userbot_alive, "me": userbot_me},
    }


@app.post("/internal/userbot-ping")
async def userbot_ping(body: dict, request: Request):
    """Userbot шлёт heartbeat каждые 30с — подтверждает что он жив."""
    check_auth(request)
    me_id = str(body.get("me_id", ""))
    me_name = str(body.get("me_name", ""))
    now = datetime.datetime.now().isoformat()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO userbot_heartbeat (id, last_ping, me_id, me_name) VALUES (1, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET last_ping=excluded.last_ping, me_id=excluded.me_id, me_name=excluded.me_name",
            (now, me_id, me_name),
        )
    return {"ok": True}


@app.get("/events")
async def get_events(
    request: Request,
    after: int = 0,
    limit: int = 100,
    wait: int = LONGPOLL_MAX_WAIT,
):
    """
    Забор событий. CRM передаёт after=<последний обработанный seq>.
    Если новых нет — держим соединение до `wait` сек, затем отдаём пустой список.
    """
    check_auth(request)
    wait = max(0, min(wait, LONGPOLL_MAX_WAIT))
    deadline = time.time() + wait

    while True:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT seq, channel_id, chat_id, kind, payload, created_at "
                "FROM events WHERE seq > ? ORDER BY seq ASC LIMIT ?",
                (after, limit),
            ).fetchall()
        if rows:
            return {
                "events": [
                    {
                        "seq": r["seq"],
                        "channel_id": r["channel_id"],
                        "chat_id": r["chat_id"],
                        "kind": r["kind"],
                        "payload": json.loads(r["payload"]),
                        "created_at": r["created_at"],
                    }
                    for r in rows
                ]
            }
        # Новых нет — ждём (long-poll)
        remaining = deadline - time.time()
        if remaining <= 0:
            return {"events": []}
        _new_event.clear()
        try:
            await asyncio.wait_for(_new_event.wait(), timeout=remaining)
        except asyncio.TimeoutError:
            return {"events": []}


@app.post("/events/ack")
async def ack_events(body: AckIn, request: Request):
    """
    CRM подтверждает: все события до last_seq включительно обработаны и
    сохранены локально (в РФ). Gateway удаляет их из зарубежной БД —
    буфер пуст, персональные данные на VPS не копятся.
    """
    check_auth(request)
    with get_db() as conn:
        cur = conn.execute("DELETE FROM events WHERE seq <= ?", (body.last_seq,))
        deleted = cur.rowcount
    return {"ok": True, "deleted": deleted}


@app.post("/send")
async def send_message(req: SendRequest, request: Request):
    """CRM кладёт исходящее сообщение. userbot заберёт из outbox и отправит."""
    check_auth(request)
    with get_db() as conn:
        # Идемпотентность: если idempotency_key уже есть — возвращаем существующий
        existing = conn.execute(
            "SELECT id, status, tg_message_id, error FROM outbox WHERE idempotency_key=?",
            (req.idempotency_key,),
        ).fetchone()
        if existing:
            return {"outbox_id": existing["id"], "status": existing["status"],
                    "tg_message_id": existing["tg_message_id"], "deduplicated": True}
        cur = conn.execute(
            "INSERT INTO outbox (idempotency_key, channel_id, chat_id, text, reply_to, status, pdf_base64, pdf_filename) "
            "VALUES (?,?,?,?,?, 'pending', ?, ?)",
            (req.idempotency_key, req.channel_id, req.chat_id, req.text, req.reply_to, req.pdf_base64, req.pdf_filename),
        )
        outbox_id = cur.lastrowid
        # Исходящее → единая история (лента чата CRM): событие kind=outgoing
        conn.execute(
            "INSERT OR IGNORE INTO events (channel_id, dedup_key, chat_id, kind, payload) "
            "VALUES (?,?,?,?,?)",
            (req.channel_id, f"outbox:{outbox_id}", req.chat_id, "outgoing",
             json.dumps({"outbox_id": outbox_id, "chat_id": req.chat_id,
                         "text": (req.text or "")[:4000],
                         "author": req.author or "evgeny",
                         "has_attachment": bool(req.pdf_base64)}, ensure_ascii=False)),
        )
    _notify_new_event()
    return {"outbox_id": outbox_id, "status": "pending", "deduplicated": False}


@app.get("/send/{outbox_id}")
async def get_send_status(outbox_id: int, request: Request):
    """Статус отправки конкретного сообщения."""
    check_auth(request)
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, status, tg_message_id, attempts, error FROM outbox WHERE id=?",
            (outbox_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="not found")
    return dict(row)


@app.post("/internal/event")
async def post_event(evt: EventIn, request: Request):
    """Userbot кладёт сюда нормализованное событие."""
    check_auth(request)
    with get_db() as conn:
        # Дедупликация по dedup_key (ON CONFLICT DO NOTHING)
        cur = conn.execute(
            "INSERT OR IGNORE INTO events (channel_id, dedup_key, chat_id, kind, payload) "
            "VALUES (?,?,?,?,?)",
            (evt.channel_id, evt.dedup_key, evt.chat_id, evt.kind, json.dumps(evt.payload, ensure_ascii=False)),
        )
        seq = cur.lastrowid
        inserted = cur.rowcount > 0
    if inserted:
        _notify_new_event()
    return {"seq": seq, "inserted": inserted}


@app.get("/internal/outbox/pending")
async def get_pending(request: Request, limit: int = 50):
    """Userbot забирает пачку исходящих для отправки (status=pending → sending)."""
    check_auth(request)
    with get_db() as conn:
        # Атомарно захватываем: pending → sending, чтобы не дублировать
        rows = conn.execute(
            "SELECT id, channel_id, chat_id, text, reply_to, pdf_base64, pdf_filename FROM outbox "
            "WHERE status='pending' ORDER BY id ASC LIMIT ?",
            (limit,),
        ).fetchall()
        ids = [r["id"] for r in rows]
        if ids:
            placeholders = ",".join("?" * len(ids))
            conn.execute(f"UPDATE outbox SET status='sending', updated_at=datetime('now') WHERE id IN ({placeholders})", ids)
    return {"items": [dict(r) for r in rows]}


@app.post("/internal/outbox/{outbox_id}/result")
async def report_outbox(outbox_id: int, body: dict, request: Request):
    """Userbot сообщает результат отправки: {ok, tg_message_id?, error?}."""
    check_auth(request)
    ok = body.get("ok", False)
    tg_mid = body.get("tg_message_id")
    error = body.get("error")
    with get_db() as conn:
        row = conn.execute("SELECT attempts FROM outbox WHERE id=?", (outbox_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="not found")
        attempts = row["attempts"] + 1
        if ok:
            conn.execute(
                "UPDATE outbox SET status='sent', tg_message_id=?, attempts=?, error=NULL, "
                "updated_at=datetime('now') WHERE id=?",
                (tg_mid, attempts, outbox_id),
            )
        else:
            # Экспоненциальный backoff через статус: если < 5 попыток — обратно в pending
            new_status = "pending" if attempts < 5 else "failed"
            conn.execute(
                "UPDATE outbox SET status=?, attempts=?, error=?, updated_at=datetime('now') WHERE id=?",
                (new_status, attempts, error, outbox_id),
            )
    # Отправляем статусное событие в общий поток (CRM узнает об доставке)
    if ok:
        _emit_status_event(outbox_id, "sent", tg_mid)
    else:
        _emit_status_event(outbox_id, "failed", None, error)
    return {"ok": True}


def _emit_status_event(outbox_id, status, tg_message_id, error=None):
    """Отправляет событие доставки в общий поток events (CRM его увидит)."""
    payload = {"type": "message_status", "outbox_id": outbox_id, "status": status,
               "tg_message_id": tg_message_id, "error": error}
    dedup = f"status:{outbox_id}:{status}:{int(time.time())}"
    with get_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO events (channel_id, dedup_key, chat_id, kind, payload) "
            "VALUES (?,?,?,?,?)",
            (0, dedup, "", "status", json.dumps(payload, ensure_ascii=False)),
        )
    _notify_new_event()


# ---------------------------------------------------------------------------
# Maintenance-воркер: чистка старых событий/исходящих (152-ФЗ, минимизация
# хранения ПДн за рубежом). Основной механизм — /events/ack от CRM;
# этот воркер — страховка: всё, что старше RETENTION_DAYS, удаляется.
# ---------------------------------------------------------------------------
async def _maintenance_worker():
    while True:
        try:
            with get_db() as conn:
                e = conn.execute(
                    "DELETE FROM events WHERE created_at < datetime('now', ?)",
                    (f"-{RETENTION_DAYS} days",),
                ).rowcount
                o = conn.execute(
                    "DELETE FROM outbox WHERE status IN ('sent','failed') "
                    "AND updated_at < datetime('now', ?)",
                    (f"-{RETENTION_DAYS} days",),
                ).rowcount
                if e or o:
                    print(f"[maintenance] удалено по возрасту >{RETENTION_DAYS} дн.: "
                          f"{e} events, {o} outbox")
        except Exception as ex:
            print(f"[maintenance] ошибка: {ex}")
        await asyncio.sleep(600)


if __name__ == "__main__":
    import uvicorn
    init_db()
    if not VALID_TOKENS:
        print("⚠️  ВНИМАНИЕ: GATEWAY_TOKEN не задан — API открыт без авторизации!")
        print("    Задайте GATEWAY_TOKEN в .env перед production-деплоем.")
    port = int(os.getenv("GATEWAY_PORT", "8443"))
    uvicorn.run(app, host="0.0.0.0", port=port)
