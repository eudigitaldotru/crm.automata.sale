import time
import asyncio
import logging
from logging.handlers import RotatingFileHandler
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from typing import Any, Literal, Optional
from pydantic import BaseModel
import os
import re
import json
import datetime
from pathlib import Path
import base64
import requests
from dotenv import load_dotenv

# Setup structured logging
log_dir = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(log_dir, exist_ok=True)
logger = logging.getLogger("automata_api")
handler = RotatingFileHandler(
    os.path.join(log_dir, "api.log"), maxBytes=10*1024*1024, backupCount=5
)
formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(name)s | %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.INFO)


# ---------- Security guards (Mimosa: SSRF/path-traversal) ----------
import ipaddress as _ipa
import socket as _sock
import urllib.request
import urllib.error
from urllib.parse import urlparse as _uparse

def _guard_external_url(url):
    """SSRF-защита для всех исходящих запросов: только http(s), хост резолвится
    в публичный IP (запрет private/loopback/link-local/metadata)."""
    pu = _uparse(str(url))
    if pu.scheme not in ("http", "https") or not pu.hostname:
        raise ValueError(f"запрещённый URL: {str(url)[:80]}")
    try:
        infos = _sock.getaddrinfo(pu.hostname, pu.port or 443, proto=_sock.IPPROTO_TCP)
    except _sock.gaierror as e:
        raise ValueError(f"DNS не разрешил {pu.hostname}: {e}")
    for info in infos:
        ip = _ipa.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or str(ip) in ("169.254.169.254",)):
            raise ValueError(f"URL ведёт на внутренний адрес: {pu.hostname} -> {ip}")

def _hc_request(url, timeout=8, context=None, headers=None, max_redirects=3, method="GET", data=None):
    """Низкоуровневый запрос через http.client; вызывающий уже прогнал гвард."""
    import http.client as _hc
    from urllib.parse import urlparse as _pu2
    for _ in range(max_redirects + 1):
        _u = _pu2(url)
        if _u.scheme == "https":
            conn = _hc.HTTPSConnection(_u.hostname, _u.port or 443, timeout=timeout, context=context)
        else:
            conn = _hc.HTTPConnection(_u.hostname, _u.port or 80, timeout=timeout)
        conn.request(method, (_u.path or "/") + (f"?{_u.query}" if _u.query else ""),
                     body=data, headers=dict(headers or {}))
        resp = conn.getresponse()
        if resp.status in (301, 302, 303, 307, 308) and resp.getheader("Location"):
            url = resp.getheader("Location")
            _guard_external_url(url)  # каждый прыжок редиректа — через гвард
            conn.close()
            continue
        return resp
    raise ValueError("слишком много редиректов")

def safe_urlopen(req, timeout=8, context=None):
    """Единая точка исходящих запросов с SSRF-гвардом (http.client; метод/тело из Request)."""
    url = getattr(req, "full_url", "")
    _guard_external_url(url)
    _hdrs = dict(getattr(req, "headers", {}) or {})
    _method = getattr(req, "get_method", lambda: "GET")()
    _data = getattr(req, "data", None)
    return _hc_request(url, timeout=timeout, context=context, headers=_hdrs,
                       method=_method, data=_data)

def safe_open_w(path, *a, **kw):
    """Единая точка записи файлов: путь канонизируется и обязан лежать в BASE_DIR."""
    rp = os.path.realpath(str(path))
    base = os.path.realpath(BASE_DIR)
    if os.path.commonpath([base, rp]) != base:
        raise ValueError(f"путь записи вне проекта: {rp}")
    return open(rp, *a, **kw)
# -------------------------------------------------------------------

app = FastAPI(title="AUTOMATA-OS API")

# Setup CORS for local React dashboard
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5001",
        "http://localhost:5173",
        "*" # Temporarily allow all for local dev
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(BASE_DIR, ".env"), override=True)

DATA_FILE = os.path.join(BASE_DIR, "dashboard", "public", "data", "data.json")
VAULT_PATH = BASE_DIR

SYNC_SECRET = os.getenv("SYNC_SECRET")
SERVER_URL = os.getenv("SERVER_URL")

from fastapi.responses import JSONResponse, FileResponse, Response

@app.middleware("http")
async def security_middleware(request: Request, call_next):
    if os.getenv("NODE_ENV") == "production":
        allowed_paths = ["/api/sync", "/api/webhook/lead", "/api/status", "/api/system/status", "/docs", "/openapi.json"]
        if request.url.path not in allowed_paths and not request.url.path.startswith("/api/invoice/"):
            token = request.headers.get("X-Sync-Secret")
            if not SYNC_SECRET or token != SYNC_SECRET:
                return JSONResponse(status_code=403, content={"error": "Forbidden. Authentication required."})
    return await call_next(request)


_remind_locks = {}  # invoice_id -> last_call_timestamp

class ApiSuccess(BaseModel):
    ok: Literal[True] = True
    data: Any = None
    duration_ms: int

class LeadPayload(BaseModel):
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    message: Optional[str] = None
    source: Optional[str] = "landing"

class ApiError(BaseModel):
    ok: Literal[False] = False
    code: str
    message: str
    duration_ms: int = 0

from typing import List, Dict

class SyncUpload(BaseModel):
    path: str
    content: str  # base64
    mtime: float

class SyncRequest(BaseModel):
    token: str
    files: Dict[str, float]
    deleted: List[str]
    uploads: List[SyncUpload]

from typing import Union
@app.post("/api/sync", response_model=Union[ApiSuccess, ApiError])
def sync_data(req: SyncRequest):
    start_t = time.time()
    
    if not SYNC_SECRET or req.token != SYNC_SECRET:
        return ApiError(code="UNAUTHORIZED", message="Invalid sync token", duration_ms=int((time.time() - start_t) * 1000))
        
    for d_path in req.deleted:
        full_path = VAULT_PATH / d_path
        if full_path.exists() and full_path.is_file():
            try:
                full_path.unlink()
                logger.info(f"[sync] Deleted from server: {d_path}")
            except Exception as e:
                logger.error(f"[sync] Error deleting {d_path}: {e}")
                
    for upload in req.uploads:
        full_path = VAULT_PATH / upload.path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            content_bytes = base64.b64decode(upload.content)
            full_path.write_bytes(content_bytes)
            os.utime(full_path, (upload.mtime, upload.mtime))
            logger.info(f"[sync] Uploaded to server: {upload.path}")
        except Exception as e:
            logger.error(f"[sync] Error uploading {upload.path}: {e}")
            
    downloads = []
    sync_dirs = ["10_Clients", "20_Inbox", "45_Tickets"]
    
    for d in sync_dirs:
        dir_path = VAULT_PATH / d
        if not dir_path.exists():
            continue
        for f in dir_path.rglob("*.md"):
            rel_path = f.relative_to(VAULT_PATH).as_posix()
            mtime = f.stat().st_mtime
            
            is_uploaded = any(u.path == rel_path for u in req.uploads)
            if is_uploaded:
                continue
                
            client_mtime = req.files.get(rel_path)
            
            if client_mtime is None or mtime > client_mtime + 1.0:
                try:
                    content_b64 = base64.b64encode(f.read_bytes()).decode('utf-8')
                    downloads.append({
                        "path": rel_path,
                        "content": content_b64,
                        "mtime": mtime
                    })
                except Exception as e:
                    logger.error(f"[sync] Error preparing download {rel_path}: {e}")
                    
    return ApiSuccess(data={"downloads": downloads}, duration_ms=int((time.time() - start_t) * 1000))

@app.get("/api/integrations/status")
def integrations_status():
    """Статусы интеграций в реальном времени: TG-контур, MAX, почта, активность.
    Светофоры для шапки дашборда и вкладки «Система»."""
    import concurrent.futures as cf
    import imaplib
    import socket
    import ssl as _ssl
    import subprocess
    import urllib.request as _ur
    from datetime import datetime
    from pathlib import Path as _Path

    res = {}

    def http_json_timeout(url, headers=None, timeout=8):
        req = _ur.Request(url, headers=headers or {})
        with safe_urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())

    # --- TG: шлюз + userbot + очередь ---
    def tg_gateway():
        env = {}
        envf = _Path(BASE_DIR) / ".env"
        for line in envf.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                env[k] = v.strip().strip('"').strip("'")
        ctx = _ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = _ssl.CERT_NONE
        t0 = time.time()
        req = _ur.Request(env.get("TG_GATEWAY_URL", "").rstrip("/") + "/health",
                          headers={"Authorization": f"Bearer {env.get('TG_GATEWAY_TOKEN','')}"})
        with safe_urlopen(req, timeout=8, context=ctx) as r:
            d = json.loads(r.read().decode())
        ms = int((time.time() - t0) * 1000)
        ub = d.get("userbot") or {}
        return {"ok": True, "ms": ms, "userbot_alive": bool(ub.get("alive")),
                "userbot": (ub.get("me") or {}).get("name", ""),
                "queue_events": d.get("events", 0), "pending_outbox": d.get("pending_outbox", 0),
                "gateway_last_seq": d.get("last_seq", 0)}

    def tg_poller():
        alive = subprocess.run(["pgrep", "-f", "tg_gateway_client.py"],
                               capture_output=True).returncode == 0
        lag = None
        try:
            cur = int((_Path(BASE_DIR) / "scripts" / ".tg_gateway_cursor").read_text().strip() or 0)
            gw = json.loads((_Path(BASE_DIR) / "scripts" / ".contact_index.json").read_text())  # placeholder
        except Exception:
            cur = None
        dl = 0
        dlf = _Path(BASE_DIR) / "logs" / "poller_failed_events.jsonl"
        if dlf.exists():
            dl = sum(1 for _ in dlf.open())
        return {"ok": alive, "cursor": cur, "dead_letter": dl}

    def max_check():
        env = {}
        for line in (_Path(BASE_DIR) / ".env").read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                env[k] = v.strip().strip('"').strip("'")
        tok = env.get("MAX_BOT_TOKEN", "")
        t0 = time.time()
        req = _ur.Request("https://botapi.max.ru/me", headers={"Authorization": tok})
        with safe_urlopen(req, timeout=8) as r:
            d = json.loads(r.read().decode())
        alive = subprocess.run(["pgrep", "-f", "max_listener.py"],
                               capture_output=True).returncode == 0
        groups = 0
        idx = _Path(BASE_DIR) / "scripts" / ".contact_index.json"
        if idx.exists():
            groups = sum(1 for v in json.loads(idx.read_text()).get("by_chat_id", {}).values())
        return {"ok": True, "ms": int((time.time() - t0) * 1000), "bot": d.get("name", "?"),
                "listener_alive": alive, "groups": groups}

    def mail_check():
        env = {}
        for line in (_Path(BASE_DIR) / ".env").read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                env[k] = v.strip().strip('"').strip("'")
        t0 = time.time()
        m = imaplib.IMAP4_SSL(env.get("EMAIL_IMAP_HOST", "imap.timeweb.ru"), timeout=8)
        m.login(env["EMAIL_USER"], env["EMAIL_PASS"])
        m.select("inbox")
        ms = int((time.time() - t0) * 1000)
        m.logout()
        # SMTP: только TCP-коннект
        t1 = time.time()
        host = env.get("EMAIL_SMTP_HOST", "smtp.timeweb.ru")
        port = int(env.get("EMAIL_SMTP_PORT", "465"))
        with socket.create_connection((host, port), timeout=6):
            smtp_ms = int((time.time() - t1) * 1000)
        # последняя успешная отправка — свежий out_email_*
        last_out = ""
        for f in sorted((_Path(BASE_DIR) / "20_Outbox").glob("out_email_*.md"), reverse=True):
            last_out = datetime.fromtimestamp(f.stat().st_mtime).strftime("%d.%m %H:%M")
            break
        return {"ok": True, "imap_ms": ms, "smtp_ms": smtp_ms, "last_send": last_out}

    def activity_check():
        last = 0.0
        for d in ("20_Inbox", "20_Outbox"):
            for f in (_Path(BASE_DIR) / d).glob("*.md"):
                last = max(last, f.stat().st_mtime)
        return {"ok": True, "last_activity": datetime.fromtimestamp(last).strftime("%d.%m %H:%M") if last else "",
                "age_min": int((time.time() - last) / 60) if last else None}

    def site_check(url):
        t0 = time.time()
        try:
            req = _ur.Request(url)
            with safe_urlopen(req, timeout=6) as r:
                return {"ok": r.status == 200, "ms": int((time.time() - t0) * 1000)}
        except Exception:
            return {"ok": False, "ms": None}

    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        f_tg = ex.submit(tg_gateway)
        f_poller = ex.submit(tg_poller)
        f_max = ex.submit(max_check)
        f_mail = ex.submit(mail_check)
        f_act = ex.submit(activity_check)
        f_mk = ex.submit(site_check, os.getenv("CRM_SAMPLE_SITE", "https://example.com/"))
        try:
            tg = f_tg.result(timeout=12)
        except Exception as e:
            tg = {"ok": False, "error": str(e)[:80]}
        try:
            poller = f_poller.result(timeout=6)
        except Exception as e:
            poller = {"ok": False, "error": str(e)[:80]}
        try:
            mx = f_max.result(timeout=12)
        except Exception as e:
            mx = {"ok": False, "error": str(e)[:80]}
        try:
            mail = f_mail.result(timeout=15)
        except Exception as e:
            mail = {"ok": False, "error": str(e)[:80]}
        try:
            act = f_act.result(timeout=6)
        except Exception as e:
            act = {"ok": False, "error": str(e)[:80]}
        try:
            mk = f_mk.result(timeout=8)
        except Exception as e:
            mk = {"ok": False, "error": str(e)[:80]}

    # отставание курсора TG
    if tg.get("ok") and poller.get("cursor") is not None:
        poller["lag"] = max(0, int(tg.get("gateway_last_seq", 0)) - int(poller["cursor"]))
    res.update({"tg_gateway": tg, "tg_poller": poller, "max": mx, "mail": mail,
                "activity": act, "mk_site": mk, "checked_at": datetime.now().strftime("%H:%M:%S")})
    # агрегаты для шапки
    def light(ok, warn=False):
        return "green" if ok else ("yellow" if warn else "red")
    res["header"] = {
        "tg": light(tg.get("ok") and tg.get("userbot_alive") and poller.get("ok")),
        "max": light(mx.get("ok") and mx.get("listener_alive")),
        "mail": light(mail.get("ok")),
    }
    return {"ok": True, "data": res}


@app.post("/api/chat/read")
def chat_mark_read(payload: dict):
    """Отметить канал прочитанным (двигается вниз списка)."""
    import sqlite3
    client = str(payload.get("client") or "")
    if not client:
        return {"ok": False}
    db = os.path.join(BASE_DIR, "crm_state.db")
    conn = sqlite3.connect(db)
    conn.executescript("CREATE TABLE IF NOT EXISTS chat_reads (client TEXT PRIMARY KEY, last_read TEXT);")
    conn.execute("INSERT INTO chat_reads (client, last_read) VALUES (?, datetime('now','localtime')) "
                 "ON CONFLICT(client) DO UPDATE SET last_read=excluded.last_read", (client,))
    conn.commit(); conn.close()
    return {"ok": True}


@app.get("/api/tasks")
def list_tasks(open_only: bool = False):
    """Задачи из 30_Tasks (голосовые навыки Джарвиса, дашборд)."""
    start_t = time.time()
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).parent))
    from extract_dashboard_data import extract_gitactive_tasks
    tasks = extract_gitactive_tasks()
    if open_only:
        tasks = [x for x in tasks if not x.get("done")]
    return {"ok": True, "tasks": tasks, "total": len(tasks),
            "duration_ms": int((time.time() - start_t) * 1000)}


@app.get("/api/sessions")
def list_sessions(limit: int = 8, tail: int = 500):
    """ZCode-сессии агентства: очередь stop-хука (20_Inbox/zcode_queue/*.json)
    + хвост последнего вывода агента из ~/.zcode/cli/agents/<sid>/agent_*/output.txt.
    Для голосового навыка голограммы («что делали агенты»)."""
    import glob as _glob
    qdir = os.path.join(BASE_DIR, "20_Inbox", "zcode_queue")
    agents_root = os.path.expanduser("~/.zcode/cli/agents")
    out = []
    if os.path.isdir(qdir):
        files = sorted(_glob.glob(os.path.join(qdir, "*.json")),
                       key=os.path.getmtime, reverse=True)[:limit]
        for f in files:
            try:
                meta = json.load(open(f, encoding="utf-8"))
            except Exception:
                continue
            sid = str(meta.get("session_id", ""))
            tail_txt = ""
            adir = os.path.join(agents_root, sid)
            if os.path.isdir(adir):
                outs = sorted(_glob.glob(os.path.join(adir, "agent_*", "output.txt")),
                              key=os.path.getmtime)
                if outs:
                    try:
                        tail_txt = open(outs[-1], encoding="utf-8",
                                        errors="replace").read()[-tail:]
                    except OSError:
                        pass
            meta["tail"] = tail_txt
            out.append(meta)
    return {"ok": True, "sessions": out, "total": len(out), "duration_ms": 0}


@app.post("/api/voice/ask")
async def voice_ask(payload: dict):
    """Мозг голограммы: абстрактные вопросы по контексту CRM.
    Быстрый путь — GLM_API_KEY (прямой вызов); без ключа — очередь на
    автоматизацию ZCode (подписка): вопрос в scripts/.voice_brain/question.json,
    ответ забирается опросом GET /api/voice/answer."""
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).parent))
    import voice_llm
    from starlette.concurrency import run_in_threadpool

    question = str(payload.get("question") or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="question обязателен")
    if voice_llm.available():
        try:
            answer = await run_in_threadpool(voice_llm.ask, question)
            return {"ok": True, "answer": answer, "queued": False, "duration_ms": 0}
        except RuntimeError as e:
            raise HTTPException(status_code=502, detail=str(e))
    q = voice_llm.enqueue(question)
    return {"ok": True, "queued": True, "id": q["id"],
            "note": "Ответит автоматизация ZCode в течение ~2 минут", "duration_ms": 0}


@app.get("/api/voice/answer")
def voice_answer(id: str):
    """Готов ли ответ моста ZCode-автоматизации на вопрос id."""
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).parent))
    import voice_llm
    return {"ok": True, **voice_llm.poll_answer(id), "duration_ms": 0}


@app.get("/api/chat/threads")
def get_chat_threads():
    """Список каналов-клиентов для левой колонки чата: клиент, каналы,
    последнее сообщение, счётчики."""
    import sqlite3
    db = os.path.join(BASE_DIR, "crm_state.db")
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT client, channel,
               COUNT(*) AS msgs,
               MAX(ts) AS last_ts,
               SUM(CASE WHEN direction='incoming' THEN 1 ELSE 0 END) AS inc
        FROM chat_messages
        WHERE client != ''
        GROUP BY client, channel
        ORDER BY last_ts DESC
    """).fetchall()
    # непрочитанные: разобранные триажем входящие после последнего прочтения канала
    import json as _json
    state_path = os.path.join(BASE_DIR, "scripts", ".inbox_triage_state.json")
    unread = {}
    try:
        st = _json.loads(open(state_path, encoding="utf-8").read())
        reads = {}
        try:
            rc = sqlite3.connect(db)
            for rr in rc.execute("SELECT client, last_read FROM chat_reads"):
                reads[rr[0]] = rr[1]
            rc.close()
        except Exception:
            pass
        for fname, info in (st.get("processed") or {}).items():
            if info.get("result") != "matched":
                continue
            cl = info.get("client") or ""
            ts = (info.get("ts") or "").replace("T", " ")
            if cl and ts > (reads.get(cl) or ""):
                unread[cl] = unread.get(cl, 0) + 1
    except Exception:
        pass

    threads = {}
    for r in rows:
        th = threads.setdefault(r["client"], {
            "client": r["client"], "last_ts": r["last_ts"], "messages": 0,
            "incoming": 0, "channels": [], "unread": unread.get(r["client"], 0)})
        th["messages"] += r["msgs"]
        th["incoming"] += r["inc"] or 0
        th["channels"].append(r["channel"])
        if r["last_ts"] > th["last_ts"]:
            th["last_ts"] = r["last_ts"]
    for th in threads.values():
        last = conn.execute(
            "SELECT author, direction, substr(text,1,70) AS t FROM chat_messages "
            "WHERE client=? ORDER BY ts DESC LIMIT 1", (th["client"],)).fetchone()
        if last:
            th["last_author"] = last["author"]
            th["last_direction"] = last["direction"]
            th["last_text"] = last["t"]
    conn.close()
    return {"ok": True, "threads": sorted(threads.values(), key=lambda x: (x.get("unread", 0) > 0, x["last_ts"]), reverse=True)}


@app.post("/api/chat/send")
async def chat_send(payload: dict):
    """Отправка сообщения из чат-UI → TG-gateway (токен живёт на сервере).
    payload: {chat_id, text, author: evgeny|jarvis, idempotency_key?}"""
    import json as _json
    import urllib.request
    import ssl
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, ".env"))
    base = os.getenv("TG_GATEWAY_URL", "").rstrip("/")
    token = os.getenv("TG_GATEWAY_TOKEN", "")
    chat_id = str(payload.get("chat_id") or "")
    text = str(payload.get("text") or "").strip()
    author = payload.get("author") if payload.get("author") in ("evgeny", "jarvis") else "evgeny"
    if not chat_id or not text:
        return {"ok": False, "error": "chat_id and text required"}
    body = _json.dumps({
        "idempotency_key": payload.get("idempotency_key") or f"ui-{int(time.time()*1000)}",
        "chat_id": chat_id, "text": text, "author": author}).encode()
    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(f"{base}/send", data=body, method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    with safe_urlopen(req, timeout=20, context=ctx) as r:
        result = _json.loads(r.read().decode())
    # Пересобрать единую ленту с задержкой: outbox-файл пишет поллер по отчёту
    # доставки через несколько секунд после отправки.
    if result.get("ok", True):
        async def _refresh_feed_later():
            import asyncio
            from starlette.concurrency import run_in_threadpool
            await asyncio.sleep(8)
            try:
                from chat_projection import update as _projection_update
                await run_in_threadpool(_projection_update)
            except Exception as e:
                print(f"[chat/send] проекция не пересобрана: {e}")
        import asyncio as _aio
        _aio.create_task(_refresh_feed_later())
    return result


@app.post("/api/voice/tts")
async def voice_tts(payload: dict):
    """Синтез речи для голограммы Джарвиса (дашборд).
    Провайдеры: ElevenLabs (если ELEVENLABS_API_KEY) → edge-tts (бесплатный).
    Отдаёт audio/mpeg; при недоступности обоих — 503, фронт фолбэкнет на speechSynthesis."""
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).parent))
    import voice_tts
    text = str(payload.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text обязателен")
    try:
        audio, ctype = await voice_tts.synth(text)
    except ValueError:
        raise HTTPException(status_code=400, detail="text обязателен")
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"TTS недоступен: {e}")
    return Response(content=audio, media_type=ctype,
                    headers={"Cache-Control": "no-store"})


@app.get("/api/chat/messages")
def get_chat_messages(client: str = None, channel: str = None, limit: int = 200):
    """Единая лента коммуникаций клиента (SQLite-проекция над 20_Inbox/20_Outbox).
    Этап «Чат как основа CRM» — 60_Reference/Chat_CRM_Architecture.md."""
    import sqlite3
    db = os.path.join(BASE_DIR, "crm_state.db")
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    q = "SELECT ts, direction, channel, author, client, contact, chat_id, text, file FROM chat_messages"
    where, args = [], []
    if client:
        where.append("client LIKE ?"); args.append(f"%{client}%")
    if channel:
        where.append("channel = ?"); args.append(channel)
    if where:
        q += " WHERE " + " AND ".join(where)
    q += " ORDER BY ts DESC LIMIT ?"
    args.append(min(limit, 1000))
    rows = [dict(r) for r in conn.execute(q, args)]
    conn.close()
    return {"ok": True, "count": len(rows), "messages": rows}


# ── «Совет» Команды Автомата: KPI + очередь решений + журнал ─────────────
COMPANY_DIR = os.path.join(str(BASE_DIR), "company")
JOURNAL_DIR = os.path.join(COMPANY_DIR, "journal")
ANSWERS_FILE = os.path.join(COMPANY_DIR, "answers.json")
_BOARD_Q_RE = re.compile(r"^###\s+(.+?)\s*$", re.M)
_BOARD_OPT_RE = re.compile(r"^-\s*\[([а-яёa-z])\]\s*(.+?)\s*$", re.M)


def _read_fm(path):
    """(frontmatter, body) из md-файла; при ошибке — ('','')."""
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        return "", ""
    m = re.match(r"^\s*---\n(.*?)\n---", text, re.DOTALL)
    return (m.group(1) if m else ""), (text[m.end():] if m else text)


def _load_answers():
    if os.path.exists(ANSWERS_FILE):
        try:
            return json.load(open(ANSWERS_FILE, encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _board_questions():
    """Вопросы «❓» из company/journal: секция '## ❓ Вопросы…', вопрос '### …',
    варианты '- [а] …'. Возвращает список с флагом answered (answers.json)."""
    answers = _load_answers()
    out = []
    if not os.path.isdir(JOURNAL_DIR):
        return out
    for name in sorted(os.listdir(JOURNAL_DIR), reverse=True):
        if not name.endswith(".md") or name == "README.md":
            continue
        fm, body = _read_fm(os.path.join(JOURNAL_DIR, name))
        if "❓" not in body:
            continue
        role = _fm_field(fm, "role") or name.rsplit("_", 1)[-1].replace(".md", "")
        date = _fm_field(fm, "date") or name[:10]
        for block in re.split(r"^##\s+", body, flags=re.M):
            if not block.startswith("❓"):
                continue
            qnum = 0
            for qm in _BOARD_Q_RE.finditer(block):
                qnum += 1
                qid = f"{name}::{qnum}"
                seg = block[qm.end():]
                nxt = _BOARD_Q_RE.search(seg)
                seg = seg[:nxt.start()] if nxt else seg
                opts = [{"key": k, "text": t} for k, t in _BOARD_OPT_RE.findall(seg)]
                if not opts:
                    continue
                a = answers.get(qid)
                out.append({"id": qid, "file": name, "date": date, "role": role,
                            "question": qm.group(1).strip(), "options": opts,
                            "answered": bool(a), "answer": a or None})
    return out


@app.get("/api/company/board")
def company_board():
    """Вкладка «Совет»: цели, дебиторка, красный список, вопросы, журнал ролей."""
    import glob
    root = str(BASE_DIR)
    goals = []
    for g in sorted(glob.glob(os.path.join(root, "55_Goals", "*.md"))):
        fm, _ = _read_fm(g)
        if _fm_field(fm, "status") != "active":
            continue
        def _num(k):
            try:
                return float(_fm_field(fm, k))
            except Exception:
                return None
        goals.append({"title": _fm_field(fm, "title") or os.path.basename(g),
                      "metric": _fm_field(fm, "metric"),
                      "current": _num("current_value"), "target": _num("target_value"),
                      "unit": _fm_field(fm, "unit") or "",
                      "direction": _fm_field(fm, "direction") or "increase",
                      "deadline": _fm_field(fm, "deadline")})

    debt_total, debt_count, oldest = 0.0, 0, ""
    for inv in glob.glob(os.path.join(root, "30_Invoices", "*.md")):
        fm, _ = _read_fm(inv)
        if _fm_field(fm, "status").lower() not in ("unpaid", "sent", "pending"):
            continue
        try:
            amt = float(_fm_field(fm, "amount"))
        except Exception:
            continue
        debt_total += amt
        debt_count += 1
        d = _fm_field(fm, "invoice_date")
        if d and (not oldest or d < oldest):
            oldest = d

    today = datetime.date.today().isoformat()
    red = []
    for t in glob.glob(os.path.join(root, "30_Tasks", f"{today}_*.md")):
        fm, _ = _read_fm(t)
        if _fm_field(fm, "status").lower() in ("done", "completed"):
            continue
        red.append(os.path.basename(t)[len(today) + 1:-3])

    journal = []
    if os.path.isdir(JOURNAL_DIR):
        names = sorted([n for n in os.listdir(JOURNAL_DIR)
                        if n.endswith(".md") and n != "README.md"], reverse=True)
        for name in names[:12]:
            fm, body = _read_fm(os.path.join(JOURNAL_DIR, name))
            journal.append({"file": name,
                            "role": _fm_field(fm, "role") or name.rsplit("_", 1)[-1][:-3],
                            "date": _fm_field(fm, "date") or name[:10],
                            "title": _fm_field(fm, "title") or name,
                            "excerpt": re.sub(r"\s+", " ", body).strip()[:400]})

    state = {}
    spath = os.path.join(COMPANY_DIR, "state.json")
    if os.path.exists(spath):
        try:
            state = json.load(open(spath, encoding="utf-8"))
        except Exception:
            state = {}
    questions = _board_questions()
    # KPI пульта «Продвижение» — совет директоров видит трафик/покрытие/SMM
    promotion = {}
    try:
        with open(os.path.join(BASE_DIR, "dashboard", "public", "data",
                               "promotion.json"), encoding="utf-8") as f:
            promotion = (json.load(f) or {}).get("kpi", {})
    except Exception:
        promotion = {}
    return {"ok": True, "goals": goals,
            "debt": {"total": round(debt_total), "count": debt_count, "oldest": oldest},
            "red_list": red,
            "questions_open": len([q for q in questions if not q["answered"]]),
            "questions": questions,
            "journal": journal,
            "promotion": promotion,
            "state": {"price_floor_active": bool(state.get("price_floor_active"))}}


@app.post("/api/company/answer")
async def company_answer(payload: dict):
    """Ответ владельца на вопрос роли (кнопка а/б/в вкладки «Совет»):
    фиксируется в company/answers.json и дописывается в journal-файл."""
    qid = str(payload.get("id") or "").strip()
    choice = str(payload.get("choice") or "").strip()
    if not qid or not choice:
        return {"ok": False, "error": "id and choice required"}
    qtext, opt_text = "", ""
    for q in _board_questions():
        if q["id"] == qid:
            qtext = q["question"]
            opt_text = next((o["text"] for o in q["options"] if o["key"] == choice), "")
            break
    if not qtext:
        return {"ok": False, "error": "question not found"}
    answers = _load_answers()
    when = datetime.datetime.now().isoformat(timespec="seconds")
    answers[qid] = {"choice": choice, "text": opt_text, "question": qtext, "answered_at": when}
    with open(ANSWERS_FILE, "w", encoding="utf-8") as f:
        json.dump(answers, f, ensure_ascii=False, indent=1)
    _jname = os.path.basename(qid.split("::")[0]).strip()
    jpath = os.path.join(JOURNAL_DIR, _jname) if _jname not in ("", ".", "..") else None
    if jpath and os.path.exists(jpath):
        with open(jpath, "a", encoding="utf-8") as f:
            f.write(f"\n> ✅ **Ответ владельца** ({when[:16].replace('T', ' ')}): {choice}) {opt_text}\n")
    return {"ok": True, "id": qid, "answer": answers[qid]}


def _fm_field(frontmatter: str, key: str):
    """Простое извлечение scalar-поля из YAML-frontmatter (без полного парса)."""
    m = re.search(rf"^{key}:\s*[\"']?(.*?)[\"']?\s*$", frontmatter, re.M)
    return m.group(1).strip() if m else ""


@app.get("/api/data", response_model=ApiSuccess)
def get_dashboard_data():
    """Возвращает данные дашборда, генерируя их на лету через модуль."""
    import sys
    start_t = time.time()
    sys.path.append(os.path.join(BASE_DIR, "scripts"))
    try:
        import extract_dashboard_data
        import importlib
        importlib.reload(extract_dashboard_data)
        data = extract_dashboard_data.build_dashboard_data()
        return ApiSuccess(data=data, duration_ms=int((time.time() - start_t) * 1000))
    except Exception as e:
        logger.error(f"[get_data] failed: {e}")
        return ApiError(code="INTERNAL_ERROR", message=str(e), duration_ms=int((time.time() - start_t) * 1000))

@app.post("/api/webhook/lead")
async def create_lead_webhook(payload: LeadPayload):
    """Прием лида с внешнего лендинга и сохранение в Vault."""
    import datetime
    import re
    start_t = time.time()
    
    clients_dir = VAULT_PATH / "10_Clients"
    clients_dir.mkdir(exist_ok=True)
    
    safe_name = re.sub(r'[\\/*?:"<>|]', "", payload.name)
    now = datetime.datetime.now()
    date_str = now.strftime("%Y-%m-%d %H:%M:%S")
    file_name = f"Лид_{safe_name}.md"
    file_path = clients_dir / file_name
    
    frontmatter = f"""---
created: {now.strftime('%Y-%m-%d')}
modified: {now.strftime('%Y-%m-%d')}
tags: [client, lead]
lifecycle: prospect
support_type: none
support_plan: ""
hours_used_current_month: 0
company_name: "{safe_name}"
contact_name: "{safe_name}"
telegram: ""
telegram_id: ""
phone: "{payload.phone or ''}"
email: "{payload.email or ''}"
source: "{payload.source}"
status: "new"
last_contact_at: "{date_str}"
rate: 3000
total_revenue: 0
invoice_amount: 0
---

# {safe_name} (Входящий Лид)

> **Жизненный цикл:** `= this.lifecycle` | **Тип:** `= this.support_type` | **План:** `= this.support_plan`

## 💬 Сообщение с сайта
{payload.message or 'Нет сообщения'}
"""
    try:
        file_path.write_text(frontmatter, encoding="utf-8")
        logger.info(f"[webhook] Created lead: {file_name}")
        return ApiSuccess(data={"status": "created", "file": file_name}, duration_ms=int((time.time() - start_t) * 1000))
    except Exception as e:
        logger.error(f"[webhook] Failed to create lead: {e}")
        return ApiError(code="WRITE_ERROR", message=str(e), duration_ms=int((time.time() - start_t) * 1000))

@app.post("/api/invoice/{invoice_number}/remind")
async def remind_invoice(invoice_number: str, request: Request):
    """Отправить напоминание об оплате счета через Telegram."""
    start_t = time.time()
    now = time.time()
    last = _remind_locks.get(invoice_number, 0)
    if now - last < 60:
        logger.warning(f"[remind] invoice={invoice_number} blocked: rate limit (60s)")
        return ApiError(code="RATE_LIMIT", message="Слишком часто. Попробуй через минуту.", duration_ms=int((time.time() - start_t) * 1000))
    
    invoice_path = None
    # 1. Search by invoice_number
    for f in (VAULT_PATH / "30_Invoices").glob("*.md"):
        try:
            content = f.read_text(encoding="utf-8")
            if f"invoice_number: {invoice_number}\n" in content or f"invoice_number: '{invoice_number}'\n" in content or f'invoice_number: "{invoice_number}"\n' in content:
                invoice_path = f
                break
        except Exception:
            pass
            
    # 2. Fallback to file name if not found
    if not invoice_path:
        fallback_path = VAULT_PATH / "30_Invoices" / f"{invoice_number}.md"
        if fallback_path.exists():
            invoice_path = fallback_path
            
    if not invoice_path:
        logger.error(f"[remind] invoice={invoice_number} not found in vault")
        return ApiError(code="INVOICE_NOT_FOUND", message=f"Счёт {invoice_number} не найден", duration_ms=int((time.time() - start_t) * 1000))

    _remind_locks[invoice_number] = now
    client_host = request.client.host if request.client else "unknown"
    logger.info(f"[remind] invoice={invoice_number} requested by={client_host}")

    script_path = os.path.join(BASE_DIR, "scripts", "send_invoice_tg.py")
    
    # We will use test mode if the script exists, but if it doesn't we just mock it for now
    if not os.path.exists(script_path):
        logger.error(f"[remind] script not found: {script_path}")
        # Just mock success for now since we haven't implemented send_invoice_tg.py yet
        logger.info(f"[remind] invoice={invoice_number} success=True (MOCK)")
        return ApiSuccess(data={"message": "Напоминание отправлено (MOCK)"}, duration_ms=int((time.time() - start_t) * 1000))

    # Run actual script async
    result = await asyncio.create_subprocess_exec(
        "python3", script_path, "--invoice", invoice_number, "--test-mode",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=BASE_DIR
    )
    stdout, stderr = await result.communicate()
    duration_ms = int((time.time() - start_t) * 1000)

    return_code_to_message = {
        10: "Счёт не найден в Vault",
        20: "Нет интернет-соединения",
        30: "Telegram API недоступен",
        40: "У клиента не указан Telegram chat_id",
    }

    if result.returncode != 0:
        err_msg = stderr.decode().strip() or stdout.decode().strip()
        logger.error(f"[remind] invoice={invoice_number} failed code={result.returncode} duration={duration_ms}ms: {err_msg}")
        
        try:
            out_json = json.loads(err_msg)
            code_str = out_json.get("code", f"UNKNOWN_ERROR_{result.returncode}")
        except json.JSONDecodeError:
            code_str = f"ERROR_{result.returncode}"
            
        user_msg = return_code_to_message.get(result.returncode, "Неизвестная ошибка")
        return ApiError(code=code_str, message=user_msg, duration_ms=duration_ms)

    logger.info(f"[remind] invoice={invoice_number} success=True duration={duration_ms}ms")
    
    try:
        out_json = json.loads(stdout.decode())
        return ApiSuccess(data=out_json, duration_ms=duration_ms)
    except json.JSONDecodeError:
        return ApiSuccess(data={"raw": stdout.decode()}, duration_ms=duration_ms)


def _find_invoice_file(invoice_number: str):
    """Найти .md файла счёта по invoice_number (точное совпадение в frontmatter)
    с fallback по имени файла. Возвращает Path или None."""
    for f in (VAULT_PATH / "30_Invoices").glob("*.md"):
        try:
            content = f.read_text(encoding="utf-8")
            if (f"invoice_number: {invoice_number}\n" in content
                    or f"invoice_number: '{invoice_number}'\n" in content
                    or f'invoice_number: "{invoice_number}"\n' in content):
                return f
        except Exception:
            pass
    fallback = VAULT_PATH / "30_Invoices" / f"{invoice_number}.md"
    if fallback.exists():
        return fallback
    return None


def _read_invoice_meta(invoice_path, field: str):
    """Прочитать произвольное поле из frontmatter файла счёта. Возвращает значение или None."""
    import yaml
    try:
        content = invoice_path.read_text(encoding="utf-8")
        match = re.search(r'^---\n(.*?)\n---', content, re.DOTALL)
        if not match:
            return None
        meta = yaml.safe_load(match.group(1)) or {}
        return meta.get(field)
    except Exception:
        return None


def _read_invoice_pdf_field(invoice_path, doc: str):
    """Прочитать invoice_pdf/act_pdf из frontmatter файла счёта. Возвращает имя файла или None."""
    return _read_invoice_meta(invoice_path, "invoice_pdf" if doc == "invoice" else "act_pdf")


@app.get("/api/invoice/{invoice_number}/pdf")
def get_invoice_pdf(invoice_number: str, doc: str = "invoice"):
    """Отдать PDF счёта или акта из 60_Documents/. HTTP-fallback для obsidian:// ссылок."""
    start_t = time.time()
    if doc not in ("invoice", "act"):
        return JSONResponse(status_code=400, content={"ok": False, "code": "BAD_DOC",
                                                      "message": "doc должен быть 'invoice' или 'act'"})

    invoice_path = _find_invoice_file(invoice_number)
    if not invoice_path:
        return JSONResponse(status_code=404, content={"ok": False, "code": "INVOICE_NOT_FOUND",
                                                      "message": f"Счёт {invoice_number} не найден"})

    pdf_name = _read_invoice_pdf_field(invoice_path, doc)
    if not pdf_name:
        return JSONResponse(status_code=404, content={"ok": False, "code": "PDF_NOT_GENERATED",
                                                      "message": f"{'Счёт' if doc == 'invoice' else 'Акт'} ещё не сгенерирован в Точке"})

    pdf_path = VAULT_PATH / "60_Documents" / pdf_name
    if not pdf_path.exists():
        return JSONResponse(status_code=404, content={"ok": False, "code": "PDF_FILE_MISSING",
                                                      "message": f"Файл {pdf_name} не найден в 60_Documents/"})

    logger.info(f"[pdf] invoice={invoice_number} doc={doc} served={pdf_name}")
    return FileResponse(str(pdf_path), media_type="application/pdf", filename=pdf_name)


@app.post("/api/invoice/{invoice_number}/generate", response_model=Union[ApiSuccess, ApiError])
async def generate_invoice_doc(invoice_number: str, doc: str = "invoice", request: Request = None):
    """Сгенерировать счёт или акт в банке Точка через scripts/tochka_api.py.
    После успеха перегенерирует data.json дашборда."""
    start_t = time.time()
    if doc not in ("invoice", "act"):
        return ApiError(code="BAD_DOC", message="doc должен быть 'invoice' или 'act'",
                       duration_ms=int((time.time() - start_t) * 1000))

    invoice_path = _find_invoice_file(invoice_number)
    if not invoice_path:
        logger.error(f"[generate] invoice={invoice_number} not found")
        return ApiError(code="INVOICE_NOT_FOUND", message=f"Счёт {invoice_number} не найден",
                       duration_ms=int((time.time() - start_t) * 1000))

    # Если PDF уже есть — не генерируем повторно (anti-spam)
    existing = _read_invoice_pdf_field(invoice_path, doc)
    if existing:
        logger.info(f"[generate] invoice={invoice_number} doc={doc} already exists={existing}")
        return ApiSuccess(data={"message": f"{'Счёт' if doc == 'invoice' else 'Акт'} уже сгенерирован",
                                "pdf": existing, "skipped": True},
                          duration_ms=int((time.time() - start_t) * 1000))

    client_host = request.client.host if request and request.client else "unknown"
    logger.info(f"[generate] invoice={invoice_number} doc={doc} requested_by={client_host}")

    # Акт требует invoice_id (генерируется только после счёта)
    cmd = ["python3", "tochka_api.py", str(invoice_path)]
    if doc == "act":
        invoice_id = _read_invoice_meta(invoice_path, "invoice_id")
        if not invoice_id:
            return ApiError(code="NO_INVOICE_ID",
                           message="Нельзя сгенерировать акт: у счёта нет invoice_id (сначала создайте счёт в Точке)",
                           duration_ms=int((time.time() - start_t) * 1000))
        cmd += ["--act", str(invoice_id)]

    result = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=os.path.join(BASE_DIR, "scripts")
    )
    stdout, stderr = await result.communicate()
    duration_ms = int((time.time() - start_t) * 1000)

    if result.returncode != 0:
        err_msg = stderr.decode().strip() or stdout.decode().strip()
        logger.error(f"[generate] invoice={invoice_number} doc={doc} failed code={result.returncode} duration={duration_ms}ms: {err_msg}")
        return ApiError(code=f"TOCHKA_ERROR_{result.returncode}",
                       message=f"Ошибка генерации в Точке: {err_msg[:300]}",
                       duration_ms=duration_ms)

    # Перегенерируем data.json, чтобы дашборд увидел новые PDF
    try:
        import sys as _sys
        _sys.path.append(os.path.join(BASE_DIR, "scripts"))
        import extract_dashboard_data as _ext
        import importlib as _il
        _il.reload(_ext)
        data = _ext.build_dashboard_data()
        tmp_path = DATA_FILE + ".tmp"
        with safe_open_w(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        os.replace(tmp_path, DATA_FILE)
    except Exception as e:
        logger.error(f"[generate] data.json rebuild failed: {e}")

    new_pdf = _read_invoice_pdf_field(invoice_path, doc)
    # Двойная защита: tochka_api.py ловит HTTPError через print и может выйти с code=0,
    # но реально ничего не создать. Если PDF не появился — считаем провалом.
    if not new_pdf:
        out_msg = stdout.decode().strip()
        logger.error(f"[generate] invoice={invoice_number} doc={doc} exit=0 but no pdf. stdout: {out_msg}")
        return ApiError(code="TOCHKA_GENERATE_FAILED",
                       message=f"Не удалось сгенерировать {'счёт' if doc == 'invoice' else 'акт'} в Точке. "
                               f"Проверьте реквизиты клиента (ИНН/КПП) и вывод: {out_msg[:250]}",
                       duration_ms=duration_ms)

    logger.info(f"[generate] invoice={invoice_number} doc={doc} success pdf={new_pdf} duration={duration_ms}ms")
    return ApiSuccess(data={"message": f"{'Счёт' if doc == 'invoice' else 'Акт'} сгенерирован в Точке",
                            "pdf": new_pdf, "refreshed": True},
                      duration_ms=duration_ms)


# ---------------------------------------------------------------------------
# Эндпоинты для режима превью счетов
# ---------------------------------------------------------------------------

@app.get("/api/invoice/{invoice_number}/email-preview", response_model=Union[ApiSuccess, ApiError])
def invoice_email_preview(invoice_number: str):
    """Возвращает сформированный subject + body письма по счёту (без отправки).
    Используется дашбордом для превью перед ручной отправкой."""
    start_t = time.time()
    duration_ms = int((time.time() - start_t) * 1000)
    invoice_path = _find_invoice_file(invoice_number)
    if not invoice_path:
        return ApiError(code="INVOICE_NOT_FOUND",
                       message=f"Счёт {invoice_number} не найден", duration_ms=duration_ms)
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).parent))
        from send_invoice_email import build_email
        email_data = build_email(str(invoice_path), send_act=False)
        if email_data is None:
            return ApiError(code="EMAIL_BUILD_FAILED",
                           message="Не удалось сформировать письмо (нет клиента/email/PDF)",
                           duration_ms=duration_ms)
        # PDF-URL для iframe в дашборде
        email_data["pdf_url"] = f"/api/invoice/{invoice_number}/pdf?doc=invoice"
        email_data["sent"] = bool(_read_invoice_meta(invoice_path, "email_status") == "sent")
        return ApiSuccess(data=email_data, duration_ms=duration_ms)
    except Exception as e:
        logger.error(f"[email-preview] {invoice_number}: {e}")
        return ApiError(code="EMAIL_PREVIEW_ERROR", message=str(e), duration_ms=duration_ms)


@app.post("/api/invoice/{invoice_number}/send-email", response_model=Union[ApiSuccess, ApiError])
async def invoice_send_email(invoice_number: str):
    """Отправляет email по счёту (точечно). Запускает send_invoice_email.py."""
    start_t = time.time()
    invoice_path = _find_invoice_file(invoice_number)
    if not invoice_path:
        duration_ms = int((time.time() - start_t) * 1000)
        return ApiError(code="INVOICE_NOT_FOUND",
                       message=f"Счёт {invoice_number} не найден", duration_ms=duration_ms)

    script_path = os.path.join(BASE_DIR, "scripts", "send_invoice_email.py")
    venv_py = os.path.join(BASE_DIR, "venv", "bin", "python3")
    interpreter = venv_py if os.path.exists(venv_py) else "python3"

    try:
        proc = await asyncio.create_subprocess_exec(
            interpreter, script_path, str(invoice_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=BASE_DIR
        )
        stdout, stderr = await proc.communicate()
        duration_ms = int((time.time() - start_t) * 1000)
        out = stdout.decode().strip()
        err = stderr.decode().strip()

        if proc.returncode != 0:
            logger.error(f"[send-email] {invoice_number} rc={proc.returncode} err={err[:200]}")
            return ApiError(code="EMAIL_SEND_FAILED",
                           message=f"Ошибка отправки: {(err or out)[:300]}",
                           duration_ms=duration_ms)

        # Парсим message_id из вывода
        message_id = None
        for line in out.splitlines():
            if "Message ID:" in line:
                import re as _re
                m = _re.search(r"Message ID:\s*(\S+)", line)
                if m:
                    message_id = m.group(1).rstrip(".")
                    break

        # Обновляем data.json
        try:
            from extract_dashboard_data import build_dashboard_data
            build_dashboard_data()
        except Exception:
            pass

        logger.info(f"[send-email] {invoice_number} success mid={message_id} duration={duration_ms}ms")
        return ApiSuccess(data={"message": "Email отправлен", "message_id": message_id},
                          duration_ms=duration_ms)
    except Exception as e:
        duration_ms = int((time.time() - start_t) * 1000)
        logger.error(f"[send-email] {invoice_number}: {e}")
        return ApiError(code="EMAIL_SEND_ERROR", message=str(e), duration_ms=duration_ms)


@app.post("/api/invoice/{invoice_number}/regenerate", response_model=Union[ApiSuccess, ApiError])
async def invoice_regenerate_pdf(invoice_number: str, doc: str = "invoice"):
    """Принудительно перегенерирует PDF в Точке (игнорирует наличие существующего PDF).
    Для случая когда счёт верный, но PDF кривой/устаревший."""
    start_t = time.time()
    invoice_path = _find_invoice_file(invoice_number)
    if not invoice_path:
        duration_ms = int((time.time() - start_t) * 1000)
        return ApiError(code="INVOICE_NOT_FOUND",
                       message=f"Счёт {invoice_number} не найден", duration_ms=duration_ms)

    script_path = os.path.join(BASE_DIR, "scripts", "tochka_api.py")
    venv_py = os.path.join(BASE_DIR, "venv", "bin", "python3")
    interpreter = venv_py if os.path.exists(venv_py) else "python3"

    cmd = [interpreter, script_path, str(invoice_path)]
    if doc == "act":
        cmd.append("--act")

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=BASE_DIR
        )
        stdout, stderr = await proc.communicate()
        duration_ms = int((time.time() - start_t) * 1000)
        out = stdout.decode().strip()
        err = stderr.decode().strip()

        if proc.returncode != 0:
            return ApiError(code="REGENERATE_FAILED",
                           message=f"Ошибка перегенерации: {(err or out)[:300]}",
                           duration_ms=duration_ms)

        new_pdf = _read_invoice_pdf_field(invoice_path, doc)
        # Обновляем data.json
        try:
            from extract_dashboard_data import build_dashboard_data
            build_dashboard_data()
        except Exception:
            pass

        logger.info(f"[regenerate] {invoice_number} doc={doc} pdf={new_pdf} duration={duration_ms}ms")
        return ApiSuccess(data={"message": "PDF перегенерирован", "pdf": new_pdf,
                                "pdf_url": f"/api/invoice/{invoice_number}/pdf?doc={doc}"},
                          duration_ms=duration_ms)
    except Exception as e:
        duration_ms = int((time.time() - start_t) * 1000)
        return ApiError(code="REGENERATE_ERROR", message=str(e), duration_ms=duration_ms)


# ---------------------------------------------------------------------------
# Шаблоны писем/TG (CRUD) и отправка в Telegram
# ---------------------------------------------------------------------------

class TemplateSaveRequest(BaseModel):
    content: str


@app.get("/api/templates/{name}", response_model=Union[ApiSuccess, ApiError])
def get_template(name: str):
    """Возвращает сырое содержимое шаблона (для редактора в дашборде)."""
    start_t = time.time()
    duration_ms = int((time.time() - start_t) * 1000)
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).parent))
    from template_utils import read_template_raw, TEMPLATE_FILES
    if name not in TEMPLATE_FILES:
        return ApiError(code="UNKNOWN_TEMPLATE",
                       message=f"Неизвестный шаблон: {name}", duration_ms=duration_ms)
    content = read_template_raw(name)
    return ApiSuccess(data={"name": name, "content": content, "file": TEMPLATE_FILES[name]},
                      duration_ms=duration_ms)


@app.post("/api/templates/{name}", response_model=Union[ApiSuccess, ApiError])
def save_template_api(name: str, req: TemplateSaveRequest):
    """Сохраняет отредактированный шаблон."""
    start_t = time.time()
    duration_ms = int((time.time() - start_t) * 1000)
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).parent))
    from template_utils import save_template, TEMPLATE_FILES
    if name not in TEMPLATE_FILES:
        return ApiError(code="UNKNOWN_TEMPLATE",
                       message=f"Неизвестный шаблон: {name}", duration_ms=duration_ms)
    ok = save_template(name, req.content)
    if not ok:
        return ApiError(code="SAVE_FAILED", message="Не удалось сохранить", duration_ms=duration_ms)
    return ApiSuccess(data={"name": name, "saved": True}, duration_ms=duration_ms)


@app.get("/api/invoice/{invoice_number}/tg-preview", response_model=Union[ApiSuccess, ApiError])
def invoice_tg_preview(invoice_number: str):
    """Рендерит TG-текст по шаблону для счёта. Возвращает {text, client_name, has_chat_id}."""
    start_t = time.time()
    duration_ms = int((time.time() - start_t) * 1000)
    invoice_path = _find_invoice_file(invoice_number)
    if not invoice_path:
        return ApiError(code="INVOICE_NOT_FOUND",
                       message=f"Счёт {invoice_number} не найден", duration_ms=duration_ms)
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).parent))
        from template_utils import render_template
        from send_invoice_email import parse_frontmatter, find_client_file, get_product_description
        from tg_outbound import resolve_chat_id

        inv_meta, content = parse_frontmatter(str(invoice_path))
        client_link = inv_meta.get("client", "").replace("[[", "").replace("]]", "").strip()
        client_path = find_client_file(inv_meta.get("client", ""))
        client_name = client_link
        contact_name = client_link
        if client_path:
            client_meta, _ = parse_frontmatter(str(client_path))
            client_name = client_meta.get("company_name") or client_link
            contact_name = client_meta.get("contact_name") or client_name

        # custom_message
        custom_message = inv_meta.get("message")
        if not custom_message:
            items = inv_meta.get("items", [])
            descs = []
            for item in items:
                if isinstance(item, str):
                    m = re.search(r"\[\[(.*?)\]\]", item)
                    if m:
                        d = get_product_description(m.group(1))
                        if d:
                            descs.append(d)
            custom_message = ". ".join(descs) if descs else ""
        if not custom_message and inv_meta.get("period"):
            custom_message = f"Работы за период: {inv_meta['period']}"

        variables = {
            "invoice_number": inv_meta.get("invoice_number", ""),
            "amount": inv_meta.get("amount", "0"),
            "period": inv_meta.get("period", ""),
            "client_name": client_name,
            "contact_name": contact_name,
            "custom_message": custom_message or "",
            "items": "; ".join(str(i) for i in inv_meta.get("items", [])),
        }
        _, tg_text = render_template("invoice_tg", variables)
        chat_id = resolve_chat_id(client_link)

        return ApiSuccess(data={
            "text": tg_text,
            "client_name": client_name,
            "has_chat_id": chat_id is not None,
            "chat_id": chat_id,
        }, duration_ms=duration_ms)
    except Exception as e:
        logger.error(f"[tg-preview] {invoice_number}: {e}")
        return ApiError(code="TG_PREVIEW_ERROR", message=str(e), duration_ms=duration_ms)


@app.post("/api/invoice/{invoice_number}/send-telegram", response_model=Union[ApiSuccess, ApiError])
def invoice_send_telegram(invoice_number: str):
    """Отправляет TG-сообщение по счёту через VPS-gateway (если есть chat_id)."""
    start_t = time.time()
    duration_ms = int((time.time() - start_t) * 1000)
    invoice_path = _find_invoice_file(invoice_number)
    if not invoice_path:
        return ApiError(code="INVOICE_NOT_FOUND",
                       message=f"Счёт {invoice_number} не найден", duration_ms=duration_ms)
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).parent))
        from template_utils import render_template
        from send_invoice_email import parse_frontmatter, find_client_file, get_product_description
        from tg_outbound import send_invoice_to_telegram

        inv_meta, content = parse_frontmatter(str(invoice_path))
        client_link = inv_meta.get("client", "").replace("[[", "").replace("]]", "").strip()
        client_path = find_client_file(inv_meta.get("client", ""))
        client_name = client_link
        contact_name = client_link
        if client_path:
            client_meta, _ = parse_frontmatter(str(client_path))
            client_name = client_meta.get("company_name") or client_link
            contact_name = client_meta.get("contact_name") or client_name

        custom_message = inv_meta.get("message") or ""
        if not custom_message and inv_meta.get("period"):
            custom_message = f"Работы за период: {inv_meta['period']}"

        variables = {
            "invoice_number": inv_meta.get("invoice_number", ""),
            "amount": inv_meta.get("amount", "0"),
            "period": inv_meta.get("period", ""),
            "client_name": client_name,
            "contact_name": contact_name,
            "custom_message": custom_message,
        }
        _, tg_text = render_template("invoice_tg", variables)

        invoice_pdf = inv_meta.get("invoice_pdf") or ""
        result = send_invoice_to_telegram(client_link, tg_text, invoice_number,
                                          invoice_pdf_path=invoice_pdf)
        duration_ms = int((time.time() - start_t) * 1000)
        if result.get("ok"):
            return ApiSuccess(data={
                "message": "Сообщение отправлено в gateway",
                "outbox_id": result.get("outbox_id"),
                "chat_id": result.get("chat_id"),
            }, duration_ms=duration_ms)
        else:
            return ApiError(code="TG_SEND_FAILED",
                           message=result.get("message") or result.get("error", "ошибка"),
                           duration_ms=duration_ms)
    except Exception as e:
        duration_ms = int((time.time() - start_t) * 1000)
        logger.error(f"[send-telegram] {invoice_number}: {e}")
        return ApiError(code="TG_SEND_ERROR", message=str(e), duration_ms=duration_ms)


# ---------------------------------------------------------------------------
# Экспресс-аудит сайта (лид-магнит)
# ---------------------------------------------------------------------------

class SiteAuditRequest(BaseModel):
    url: str


class AuditLeadRequest(BaseModel):
    url: str
    contact: str
    name: str = ""
    results: dict = {}


def _run_site_audit(url: str) -> dict:
    """Быстрый аудит сайта: 5 метрик за несколько секунд. Без внешних API."""
    import requests as _rq
    import socket
    import ssl as _ssl
    from urllib.parse import urlparse

    # Нормализация URL
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    parsed = urlparse(url)
    domain = parsed.hostname or url

    result = {
        "url": url,
        "domain": domain,
        "checks": {},
    }

    # --- 1. Доступность + скорость ответа ---
    ttfb_ms = None
    html = ""
    try:
        r = _rq.get(url, timeout=10, verify=False, allow_redirects=True,
                    headers={"User-Agent": "Automata-Audit/1.0"})
        ttfb_ms = int(r.elapsed.total_seconds() * 1000)
        html = r.text if r.status_code == 200 else ""
        result["checks"]["uptime"] = {
            "score": 100 if r.status_code == 200 else 40,
            "label": "Доступность",
            "detail": f"HTTP {r.status_code}, ответ за {ttfb_ms}мс",
        }
    except Exception as e:
        result["checks"]["uptime"] = {"score": 0, "label": "Доступность",
                                      "detail": f"Сайт недоступен: {str(e)[:80]}"}
        result["overall"] = 0
        return result

    # --- 2. Скорость (TTFB proxy) ---
    if ttfb_ms is not None:
        if ttfb_ms < 300: speed_score, speed_note = 100, "отлично"
        elif ttfb_ms < 800: speed_score, speed_note = 75, "хорошо"
        elif ttfb_ms < 2000: speed_score, speed_note = 50, "медленно"
        else: speed_score, speed_note = 20, "очень медленно"
        result["checks"]["speed"] = {
            "score": speed_score, "label": "Скорость (TTFB)",
            "detail": f"{ttfb_ms}мс — {speed_note}",
        }

    # --- 3. SSL-сертификат ---
    try:
        ctx = _ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = _ssl.CERT_NONE
        ssl_detail = "Валидный, HTTPS работает"
        ssl_score = 100
        with socket.create_connection((domain, 443), timeout=8) as sock:
            with ctx.wrap_socket(sock, server_hostname=domain) as ssock:
                import datetime as _dt
                not_after = ssock.getpeercert().get("notAfter") if ssock.getpeercert() else None
                if not_after:
                    try:
                        exp = _dt.datetime.strptime(not_after, "%b %d %H:%M:%S %Y GMT")
                        days_left = (exp - _dt.datetime.utcnow()).days
                        if days_left < 7:
                            ssl_score, ssl_detail = 20, f"Истекает через {days_left} дн.!"
                        elif days_left < 30:
                            ssl_score, ssl_detail = 60, f"Истекает через {days_left} дн."
                        else:
                            ssl_detail = f"Валидный, осталось {days_left} дн."
                    except Exception:
                        pass
        result["checks"]["ssl"] = {"score": ssl_score, "label": "SSL-сертификат", "detail": ssl_detail}
    except Exception:
        result["checks"]["ssl"] = {"score": 0, "label": "SSL-сертификат",
                                   "detail": "Не удалось установить HTTPS"}

    # --- 4. SEO-мета (title, description, OG, canonical, h1) ---
    import re as _re
    seo_points = 0
    seo_notes = []
    title = _re.search(r"<title[^>]*>(.*?)</title>", html, _re.I | _re.S)
    if title and 10 < len(title.group(1).strip()) < 70:
        seo_points += 25
    else:
        seo_notes.append("title отсутствует/неоптимальный")
    meta_desc = _re.search(r'<meta\s+name=["\']description["\'][^>]*content=["\'](.*?)["\']', html, _re.I)
    if meta_desc and len(meta_desc.group(1).strip()) > 50:
        seo_points += 25
    else:
        seo_notes.append("meta description отсутствует")
    if _re.search(r'property=["\']og:', html, _re.I):
        seo_points += 20
    else:
        seo_notes.append("нет OpenGraph (шаринг в соцсетях)")
    if _re.search(r'rel=["\']canonical["\']', html, _re.I):
        seo_points += 15
    else:
        seo_notes.append("нет canonical")
    if _re.search(r"<h1[^>]*>", html, _re.I):
        seo_points += 15
    else:
        seo_notes.append("нет H1")
    result["checks"]["seo"] = {
        "score": seo_points, "label": "SEO-мета",
        "detail": "Проблемы: " + (", ".join(seo_notes) if seo_notes else "нет"),
    }

    # --- 5. GEO/LLM-ready (robots.txt, sitemap, llms.txt, Schema.org) ---
    geo_points = 0
    geo_notes = []
    for path, pts, note in [("/robots.txt", 25, "нет robots.txt"),
                             ("/sitemap.xml", 25, "нет sitemap.xml"),
                             ("/llms.txt", 30, "нет llms.txt (AI-видимость!)")]:
        try:
            rr = _rq.get(url.rstrip("/") + path, timeout=6, verify=False)
            if rr.status_code == 200 and len(rr.text) > 10:
                geo_points += pts
            else:
                geo_notes.append(note)
        except Exception:
            geo_notes.append(note)
    if _re.search(r'application/ld\+json', html, _re.I):
        geo_points += 20
    else:
        geo_notes.append("нет Schema.org разметки")
    result["checks"]["geo"] = {
        "score": geo_points, "label": "GEO/AI-готовность",
        "detail": "Проблемы: " + (", ".join(geo_notes) if geo_notes else "нет"),
    }

    # Общая оценка (среднее)
    scores = [c["score"] for c in result["checks"].values()]
    result["overall"] = round(sum(scores) / len(scores)) if scores else 0
    return result


@app.post("/api/site-audit", response_model=Union[ApiSuccess, ApiError])
def site_audit(req: SiteAuditRequest):
    """Экспресс-аудит сайта: 5 проверок за секунды. Лид-магнит."""
    start_t = time.time()
    duration_ms = int((time.time() - start_t) * 1000)
    url = (req.url or "").strip()
    if not url or "." not in url:
        return ApiError(code="INVALID_URL", message="Укажите корректный URL сайта", duration_ms=duration_ms)
    try:
        import warnings
        warnings.filterwarnings("ignore")
        result = _run_site_audit(url)
        return ApiSuccess(data=result, duration_ms=int((time.time() - start_t) * 1000))
    except Exception as e:
        logger.error(f"[site-audit] {url}: {e}")
        return ApiError(code="AUDIT_ERROR", message=str(e), duration_ms=int((time.time() - start_t) * 1000))


@app.post("/api/site-audit/save-lead", response_model=Union[ApiSuccess, ApiError])
def audit_save_lead(req: AuditLeadRequest):
    """Сохраняет результат аудита как лид в 15_Leads/ (захват контакта)."""
    start_t = time.time()
    duration_ms = int((time.time() - start_t) * 1000)
    import uuid as _uuid
    try:
        leads_dir = os.path.join(BASE_DIR, "15_Leads")
        os.makedirs(leads_dir, exist_ok=True)
        lead_id = _uuid.uuid4().hex[:6]
        fname = f"audit_lead_{time.strftime('%Y-%m-%d_%H-%M')}_{(req.url or 'site').replace('/', '_')[:20]}.md"
        contact = (req.contact or "").strip()
        is_email = "@" in contact and "." in contact
        is_phone = contact.replace("+", "").replace(" ", "").replace("-", "").replace("(", "").replace(")", "").isdigit()
        overall = req.results.get("overall", 0)
        content = f"""---
created: {time.strftime("%Y-%m-%d")}
source: site-audit
status: new
name: {req.name or 'Аудит ' + (req.results.get('domain') or req.url)}
{"email: \"" + contact + "\"" if is_email else ""}
{"phone: \"" + contact + "\"" if is_phone else ""}
audit_url: "{req.url}"
audit_score: {overall}
---
# Лид с экспресс-аудита: {req.results.get('domain', req.url)}

**Контакт:** {contact or 'не указан'}
**Общая оценка сайта:** {overall}/100

## Результаты проверок
"""
        for key, chk in (req.results.get("checks") or {}).items():
            content += f"- **{chk.get('label', key)}:** {chk.get('score', '?')}/100 — {chk.get('detail', '')}\n"
        content += f"\nАудит выполнен {time.strftime('%d.%m.%Y %H:%M')} через дашборд AUTOMATA-CRM.\n"
        (Path(leads_dir) / fname).write_text(content, encoding="utf-8")
        logger.info(f"[site-audit] lead saved: {fname}")
        return ApiSuccess(data={"saved": True, "file": fname}, duration_ms=int((time.time() - start_t) * 1000))
    except Exception as e:
        return ApiError(code="LEAD_SAVE_ERROR", message=str(e), duration_ms=int((time.time() - start_t) * 1000))


@app.post("/api/system/refresh", response_model=ApiSuccess)
def refresh_system():
    start_t = time.time()
    return ApiSuccess(data={"message": "System refreshed"}, duration_ms=int((time.time() - start_t) * 1000))

@app.post("/api/refresh", response_model=Union[ApiSuccess, ApiError])
def refresh_dashboard():
    start_t = time.time()
    try:
        import sys
        sys.path.append(os.path.join(BASE_DIR, "scripts"))
        import extract_dashboard_data
        import importlib
        importlib.reload(extract_dashboard_data)
        data = extract_dashboard_data.build_dashboard_data()
        
        # Save to disk
        try:
            with safe_open_w(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        except Exception as disk_err:
            logger.error(f"[refresh_dashboard] failed to write to disk: {disk_err}")
            
        return ApiSuccess(data=data, duration_ms=int((time.time() - start_t) * 1000))
    except Exception as e:
        logger.error(f"[refresh_dashboard] failed: {e}")
        return ApiError(code="INTERNAL_ERROR", message=str(e), duration_ms=int((time.time() - start_t) * 1000))

@app.post("/api/sync-tasks", response_model=Union[ApiSuccess, ApiError])
def sync_tasks():
    start_t = time.time()
    import subprocess
    import sys
    import os
    scripts_dir = BASE_DIR / "scripts"
    try:
        # Run check_statuses.py and reconcile.py in the context of the virtualenv python
        subprocess.run([sys.executable, "check_statuses.py"], cwd=str(scripts_dir), check=False)
        subprocess.run([sys.executable, "reconcile.py"], cwd=str(scripts_dir), check=False)
        
        sys.path.append(os.path.join(BASE_DIR, "scripts"))
        import extract_dashboard_data
        import importlib
        importlib.reload(extract_dashboard_data)
        data = extract_dashboard_data.build_dashboard_data()
        
        # Write the updated dashboard data directly to the static data.json file
        try:
            with safe_open_w(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        except Exception as disk_err:
            logger.error(f"[sync_tasks] failed to write to disk: {disk_err}")
            
        # Update overtime status file to show fresh sync on dashboard
        status_file = os.path.join(scripts_dir, ".status_overtime.json")
        try:
            import datetime
            with safe_open_w(status_file, 'w', encoding='utf-8') as f:
                json.dump({
                    "last_run": datetime.datetime.now().isoformat(),
                    "status": "success"
                }, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[sync_tasks] failed to write status file: {e}")
            
        return ApiSuccess(data={"message": "Sync successful"}, duration_ms=int((time.time() - start_t) * 1000))
    except Exception as e:
        logger.error(f"[sync_tasks] failed: {e}")
        return ApiError(code="INTERNAL_ERROR", message=str(e), duration_ms=int((time.time() - start_t) * 1000))

@app.post("/api/refresh-monitoring", response_model=Union[ApiSuccess, ApiError])
def refresh_monitoring():
    start_t = time.time()
    import subprocess
    import sys
    import os
    
    scripts_dir = os.path.join(BASE_DIR, "scripts")
    checkers = [
        "uptime_check.py",
        "ssl_check.py",
        "whois_check.py",
        "security_check.py",
        "pagespeed_check.py"
    ]
    
    outputs = []
    try:
        for checker in checkers:
            path = os.path.join(scripts_dir, checker)
            if os.path.exists(path):
                logger.info(f"[refresh_monitoring] running {checker}...")
                # 90s timeout for PageSpeed / WHOIS
                res = subprocess.run([sys.executable, path], capture_output=True, text=True, timeout=90)
                if res.returncode != 0:
                    logger.error(f"[refresh_monitoring] {checker} failed: {res.stderr}")
                    outputs.append(f"{checker}: Failed ({res.stderr.strip()})")
                else:
                    outputs.append(f"{checker}: OK")
            else:
                outputs.append(f"{checker}: Not found")
                
        return ApiSuccess(data={"message": "Monitoring refreshed successfully", "details": "; ".join(outputs)}, duration_ms=int((time.time() - start_t) * 1000))
    except Exception as e:
        logger.error(f"[refresh_monitoring] error: {e}")
        return ApiError(code="INTERNAL_ERROR", message=str(e), duration_ms=int((time.time() - start_t) * 1000))

@app.post("/api/start-service", response_model=ApiSuccess)
def start_dashboard_service(payload: dict):
    start_t = time.time()
    service = payload.get("service")
    import subprocess
    import os
    
    scripts_dir = BASE_DIR / "scripts"
    
    if service == "tg_listener":
        # Check if already running
        try:
            out = subprocess.check_output(["pgrep", "-f", "tg_listener.py"]).decode()
            if len(out.strip()) > 0:
                return ApiSuccess(data={"message": "Already running"}, duration_ms=int((time.time() - start_t) * 1000))
        except Exception:
            pass
            
        subprocess.Popen(["python3", "tg_listener.py"], cwd=str(scripts_dir))
        return ApiSuccess(data={"message": "TG Listener started"}, duration_ms=int((time.time() - start_t) * 1000))
        
    elif service == "overtime":
        try:
            result = subprocess.run(["python3", "reconcile.py"], cwd=str(scripts_dir), capture_output=True)
            return ApiSuccess(data={"output": result.stdout.decode()}, duration_ms=int((time.time() - start_t) * 1000))
        except Exception as e:
            return ApiError(code="INTERNAL_ERROR", message=str(e), duration_ms=int((time.time() - start_t) * 1000))
            
    return ApiError(code="UNKNOWN_SERVICE", message="Unknown service", duration_ms=int((time.time() - start_t) * 1000))

@app.get("/api/system/status")
def system_status():
    import subprocess
    import urllib.request
    import json
    
    if SERVER_URL:
        try:
            req = urllib.request.Request(f"{SERVER_URL.rstrip('/')}/api/system/status")
            with safe_urlopen(req, timeout=2) as response:
                if response.status == 200:
                    return json.loads(response.read().decode())
        except Exception:
            pass # Fallback to local
    
    def is_running(script_name):
        try:
            out = subprocess.check_output(["pgrep", "-f", script_name]).decode()
            return len(out.strip()) > 0
        except Exception:
            return False
            
    return {
        "Telegram Listener": is_running("tg_listener.py"),
        "SLA Timer": is_running("sla_timer.py"),
        "API Server": True,
        "SLA Monitor": is_running("monitoring_daemon.py")
    }

@app.get("/api/status")
def dashboard_header_status():
    import subprocess
    import os
    import json
    import urllib.request
    
    if SERVER_URL:
        try:
            req = urllib.request.Request(f"{SERVER_URL.rstrip('/')}/api/status")
            with safe_urlopen(req, timeout=2) as response:
                if response.status == 200:
                    return json.loads(response.read().decode())
        except Exception:
            pass # Fallback to local
            
    def is_running(script_name):
        try:
            out = subprocess.check_output(["pgrep", "-f", script_name]).decode()
            return len(out.strip()) > 0
        except Exception:
            return False

    # TG-статус: пингуем зарубежный gateway (userbot + связь с VPS),
    # а не локальный tg_listener.py (он сломан, заменён на gateway-клиент).
    tg_gateway_url = os.getenv("TG_GATEWAY_URL", "")
    tg_gateway_token = os.getenv("TG_GATEWAY_TOKEN", "")
    tg_active = False
    tg_me = None
    if tg_gateway_url:
        try:
            req = urllib.request.Request(f"{tg_gateway_url.rstrip('/')}/health")
            if tg_gateway_token:
                req.add_header("Authorization", f"Bearer {tg_gateway_token}")
            with safe_urlopen(req, timeout=8) as resp:
                gh = json.loads(resp.read().decode("utf-8"))
                ub = gh.get("userbot", {}) or {}
                tg_active = bool(ub.get("alive"))
                tg_me = ub.get("me")
        except Exception:
            tg_active = False
    
    # Overtime sync status
    overtime_status = {"last_run": None, "status": "never"}
    overtime_file = os.path.join(BASE_DIR, "scripts", ".status_overtime.json")
    if os.path.exists(overtime_file):
        with open(overtime_file, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
                overtime_status = data
            except:
                pass 
                
    # Monitoring status
    monitoring_status = {"active": False, "status": "stale", "issues": 0}
    mon_file = os.path.join(BASE_DIR, "dashboard", "public", "data", "monitoring.json")
    if os.path.exists(mon_file):
        try:
            mtime = os.path.getmtime(mon_file)
            is_fresh = (time.time() - mtime) < (3 * 60 * 60)
            
            with open(mon_file, "r") as f:
                data = json.load(f)
                
            issues = 0
            for s in data:
                if s.get("status") == "down" or s.get("expiryDate") == "Error":
                    issues += 1
                elif s.get("expiryDate") and s.get("expiryDate") not in ["Unknown", "Error"]:
                    # check days
                    import datetime
                    exp = datetime.datetime.fromisoformat(s["expiryDate"].replace("Z", "+00:00"))
                    if (exp.timestamp() - time.time()) < (7 * 24 * 60 * 60):
                        issues += 1
                        
            monitoring_status = {
                "active": is_fresh,
                "status": ("issues" if issues > 0 else "ok") if is_fresh else "stale",
                "issues": issues
            }
        except Exception as e:
            pass
            
    return {
        "telegram_listener": {
            "active": tg_active,
            "status": "running" if tg_active else "stopped",
            "me": tg_me
        },
        "overtime_sync": overtime_status,
        "monitoring": monitoring_status
    }

@app.get("/api/system/logs")
def system_logs():
    import subprocess
    from fastapi.responses import PlainTextResponse
    log_path = os.path.join(log_dir, "api.log")
    if not os.path.exists(log_path):
        return PlainTextResponse("Лог файл не найден.")
    try:
        out = subprocess.check_output(["tail", "-n", "50", log_path]).decode()
        return PlainTextResponse(out)
    except Exception as e:
        return PlainTextResponse(f"Ошибка чтения логов: {e}")

@app.post("/api/actions/run")
async def run_action(action: str):
    from fastapi.responses import PlainTextResponse
    import subprocess
    
    script_map = {
        "reconcile": "reconcile.py",
        "auto_invoice": "auto_invoice_monthly.py",
        "extract_data": "extract_dashboard_data.py"
    }
    
    if action not in script_map:
        return PlainTextResponse(f"Неизвестное действие: {action}", status_code=400)
        
    script_path = os.path.join(BASE_DIR, "scripts", script_map[action])
    if not os.path.exists(script_path):
        # Fallback to run without errors if script doesn't exist yet
        return PlainTextResponse(f"Успех (Заглушка): Скрипт {script_map[action]} не найден, но команда принята.")
        
    try:
        proc = await asyncio.create_subprocess_exec(
            "python3", script_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=BASE_DIR
        )
        # We don't want to wait for extract_data to finish entirely if it takes too long, but let's just wait
        stdout, stderr = await proc.communicate()

        output = stdout.decode().strip() or stderr.decode().strip() or "Успешно выполнено."
        return PlainTextResponse(output)
    except Exception as e:
        return PlainTextResponse(f"Ошибка запуска: {e}", status_code=500)


@app.post("/api/actions/run-stream")
async def run_action_stream(action: str, request: Request):
    """
    Streaming-вариант /actions/run: запускает скрипт и отдаёт его stdout
    построчно в реальном времени (text/event-stream).
    Фронтенд читает поток через fetch().body.getReader().
    Каждая строка оборачивается как SSE 'data: ...\\n\\n'.
    """
    from fastapi.responses import StreamingResponse
    from urllib.parse import parse_qs

    script_map = {
        "reconcile": "reconcile.py",
        "auto_invoice": "auto_invoice_monthly.py",
        "auto_invoice_preview": "auto_invoice_monthly.py",
        "extract_data": "extract_dashboard_data.py"
    }

    if action not in script_map:
        async def err():
            yield f"data: ❌ Неизвестное действие: {action}\n\n"
        return StreamingResponse(err(), media_type="text/event-stream")

    script_path = os.path.join(BASE_DIR, "scripts", script_map[action])
    if not os.path.exists(script_path):
        async def err():
            yield f"data: ❌ Скрипт {script_map[action]} не найден.\n\n"
        return StreamingResponse(err(), media_type="text/event-stream")

    # Определяем интерпретатор: используем venv если есть, иначе python3
    venv_py = os.path.join(BASE_DIR, "venv", "bin", "python3")
    interpreter = venv_py if os.path.exists(venv_py) else "python3"

    # Дополнительные аргументы для конкретных действий
    extra_args = []
    if action == "auto_invoice_preview":
        extra_args.append("--preview")
    # Переопределение периода (?period=Сентябрь+2026) — для досрочного выставления
    period_override = request.query_params.get("period", "").strip()
    if period_override and action in ("auto_invoice", "auto_invoice_preview"):
        extra_args.append(f"--period={period_override}")

    async def stream_script():
        try:
            proc = await asyncio.create_subprocess_exec(
                interpreter, script_path, *extra_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,  # stderr сливается в stdout
                cwd=BASE_DIR
            )
            # Построчное чтение stdout, отдаём каждую строку как SSE-событие
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                text = line.decode(errors="replace").rstrip("\n\r")
                if text:
                    yield f"data: {text}\n\n"
            await proc.wait()
            rc = proc.returncode
            if rc == 0:
                yield "data: ✅__DONE__\n\n"
            else:
                yield f"data: ❌__DONE__(rc={rc})\n\n"
        except asyncio.CancelledError:
            # Клиент отключился — убиваем подпроцесс
            try:
                proc.kill()
            except Exception:
                pass
            raise
        except Exception as e:
            yield f"data: ❌ Ошибка: {e}\n\n"

    return StreamingResponse(stream_script(), media_type="text/event-stream")

from pydantic import BaseModel
class OpenFileRequest(BaseModel):
    path: str

class CloseTaskRequest(BaseModel):
    hours: float = 0.0

@app.post("/api/system/open-file", response_model=Union[ApiSuccess, ApiError])
def open_file_api(req: OpenFileRequest):
    import subprocess
    start_t = time.time()
    try:
        # Try VS Code first, then cursor, then xdg-open
        for cmd in ["code", "cursor", "xdg-open"]:
            try:
                subprocess.run([cmd, req.path], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return ApiSuccess(data={"message": f"Открыто через {cmd}"}, duration_ms=int((time.time() - start_t) * 1000))
            except Exception:
                continue
        return ApiError(code="OPEN_FAILED", message="Не найдено приложение для открытия файла", duration_ms=int((time.time() - start_t) * 1000))
    except Exception as e:
        return ApiError(code="INTERNAL_ERROR", message=str(e), duration_ms=int((time.time() - start_t) * 1000))


def _set_frontmatter_field(frontmatter_text: str, field: str, value: str) -> str:
    """Безопасно обновить/добавить поле в YAML frontmatter (построчно).
    Не использует yaml-парсер, чтобы сохранить форматирование и порядок полей
    для смешанных форматов задач (tpl_task / dev_task)."""
    # Попытка заменить существующее поле: ^field: <value>$  (включая значения в кавычках)
    pattern = re.compile(rf'^({re.escape(field)}:)\s*.*$', re.MULTILINE)
    if pattern.search(frontmatter_text):
        return pattern.sub(rf'\1 {value}', frontmatter_text, count=1)
    # Поля нет — добавляем в конец блока (перед будет стоять закрывающий ---, но мы работаем
    # только с текстом между ---, поэтому просто дописываем строку)
    return frontmatter_text.rstrip() + f"\n{field}: {value}"


# ---------------------------------------------------------------------------
# Генерация договоров на сопровождение (scripts/generate_framework_contract.py)
# ---------------------------------------------------------------------------

class ContractGenerateRequest(BaseModel):
    client: str
    number: Optional[str] = None
    template: Optional[str] = None
    export: bool = False
    appendices: Optional[List[str]] = None


class ContractExportRequest(BaseModel):
    file: str


@app.get("/api/contracts/appendices", response_model=Union[ApiSuccess, ApiError])
def get_contract_appendices():
    """Реестр приложений договора — дашборд строит по нему чекбоксы в модалке."""
    start_t = time.time()
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).parent))
        import importlib as _il
        import generate_framework_contract as _gfc
        _il.reload(_gfc)
        return ApiSuccess(data=_gfc.get_appendix_registry(),
                          duration_ms=int((time.time() - start_t) * 1000))
    except Exception as e:
        logger.error(f"[contracts/appendices] {e}")
        return ApiError(code="APPENDICES_ERROR", message=str(e),
                        duration_ms=int((time.time() - start_t) * 1000))


def _run_contract_export(md_file: str):
    """Запустить scripts/export_contract.py (md → docx + pdf). Возвращает dict или бросает Exception."""
    import subprocess as _sp
    script = os.path.join(BASE_DIR, "scripts", "export_contract.py")
    proc = _sp.run(["python3", script, md_file], capture_output=True, text=True,
                   timeout=300, cwd=str(BASE_DIR))
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout).strip()[:300])
    import json as _json
    return _json.loads(proc.stdout.strip().splitlines()[-1])


@app.post("/api/contracts/export", response_model=Union[ApiSuccess, ApiError])
def export_contract_endpoint(req: ContractExportRequest):
    """Собрать DOCX + PDF из существующего .md договора (пайплайн it-report:
    pandoc + contract_reference.docx → LibreOffice headless)."""
    start_t = time.time()
    duration_ms = lambda: int((time.time() - start_t) * 1000)

    md_name = os.path.basename((req.file or "").strip())
    if not md_name.lower().endswith(".md"):
        return ApiError(code="BAD_FILE", message="Ожидается .md файл договора",
                        duration_ms=duration_ms())
    md_path = VAULT_PATH / "60_Documents" / "Contracts" / md_name
    if not md_path.exists():
        return ApiError(code="FILE_NOT_FOUND", message=f"Файл не найден: {md_name}",
                        duration_ms=duration_ms())

    logger.info(f"[contracts/export] {md_name}")
    try:
        result = _run_contract_export(str(md_path))
    except Exception as e:
        logger.error(f"[contracts/export] {md_name}: {e}")
        return ApiError(code="EXPORT_ERROR", message=str(e), duration_ms=duration_ms())

    return ApiSuccess(data={"message": "DOCX + PDF собраны",
                            "docx": result["docx"], "pdf": result["pdf"]},
                      duration_ms=duration_ms())


@app.post("/api/contracts/generate", response_model=Union[ApiSuccess, ApiError])
def generate_contract_endpoint(req: ContractGenerateRequest):
    """Сгенерировать договор на сопровождение из карточки клиента по шаблону
    90_Templates/tpl_contract_support.md. При коллизии имени — суффикс _v2, _v3."""
    start_t = time.time()
    duration_ms = lambda: int((time.time() - start_t) * 1000)

    client_name = req.client.strip()
    if not client_name or "/" in client_name or "\\" in client_name or ".." in client_name:
        return ApiError(code="BAD_CLIENT", message="Некорректное имя клиента",
                        duration_ms=duration_ms())
    client_path = VAULT_PATH / "10_Clients" / f"{client_name}.md"
    if not client_path.exists():
        return ApiError(code="CLIENT_NOT_FOUND",
                        message=f"Карточка клиента не найдена: 10_Clients/{client_name}.md",
                        duration_ms=duration_ms())

    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).parent))
        import importlib as _il
        import generate_framework_contract as _gfc
        _il.reload(_gfc)
        # req.template — ID из реестра шаблонов («contract_support») или прямой путь
        template_path = req.template
        if template_path and not os.path.isabs(template_path) and not os.path.exists(template_path):
            from template_utils import get_template_path
            resolved = get_template_path(template_path)
            if resolved:
                template_path = str(resolved)
        out_path = _gfc.generate_framework_contract(str(client_path), req.number,
                                                    send=False,
                                                    template_path=template_path,
                                                    appendices=req.appendices)
    except Exception as e:
        logger.error(f"[contracts/generate] {req.client}: {e}")
        return ApiError(code="CONTRACT_GENERATE_ERROR", message=str(e),
                        duration_ms=duration_ms())

    file_name = os.path.basename(out_path)
    logger.info(f"[contracts/generate] {req.client} -> {file_name}")
    data = {"message": f"Договор создан: {file_name}",
            "file": file_name,
            "path": f"60_Documents/Contracts/{file_name}"}

    # Опционально сразу собираем DOCX + PDF
    if req.export:
        try:
            exported = _run_contract_export(str(out_path))
            data["docx"] = exported["docx"]
            data["pdf"] = exported["pdf"]
            data["message"] += " + DOCX/PDF"
        except Exception as e:
            logger.error(f"[contracts/generate] export failed: {e}")
            data["export_error"] = str(e)

    return ApiSuccess(data=data, duration_ms=duration_ms())


# ---------------------------------------------------------------------------
# Универсальное создание сущностей (задачи, счета, акты...)
# Реестр и рендереры: scripts/create_entity.py. Obsidian Vault — единственная БД:
# эндпоинт только создаёт .md-файл и перегенерирует data.json.
# ---------------------------------------------------------------------------

class EntityCreateRequest(BaseModel):
    data: Dict[str, Any] = {}


@app.get("/api/entities/schema", response_model=Union[ApiSuccess, ApiError])
def get_entity_schemas():
    """Схемы полей всех сущностей — дашборд строит по ним форму создания."""
    start_t = time.time()
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).parent))
        from create_entity import get_schemas
        return ApiSuccess(data=get_schemas(), duration_ms=int((time.time() - start_t) * 1000))
    except Exception as e:
        logger.error(f"[entities/schema] {e}")
        return ApiError(code="SCHEMA_ERROR", message=str(e),
                        duration_ms=int((time.time() - start_t) * 1000))


@app.post("/api/entities/{entity_type}", response_model=Union[ApiSuccess, ApiError])
def create_entity_endpoint(entity_type: str, req: EntityCreateRequest):
    """Создать сущность (task, ...) в Vault из JSON полей. Возвращает созданный файл."""
    start_t = time.time()
    duration_ms = lambda: int((time.time() - start_t) * 1000)
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).parent))
        from create_entity import create_entity, rebuild_dashboard, EntityError
    except Exception as e:
        logger.error(f"[entities/{entity_type}] import failed: {e}")
        return ApiError(code="IMPORT_ERROR", message=str(e), duration_ms=duration_ms())

    try:
        result = create_entity(entity_type, req.data)
    except EntityError as e:
        logger.warning(f"[entities/{entity_type}] validation: {e}")
        return ApiError(code="VALIDATION_ERROR", message=str(e), duration_ms=duration_ms())
    except Exception as e:
        logger.error(f"[entities/{entity_type}] create failed: {e}")
        return ApiError(code="CREATE_ERROR", message=str(e), duration_ms=duration_ms())

    # Перегенерируем data.json, чтобы новая сущность появилась на дашборде сразу
    try:
        rebuild_dashboard()
        result["refreshed"] = True
    except Exception as e:
        logger.error(f"[entities/{entity_type}] data.json rebuild failed: {e}")

    logger.info(f"[entities/{entity_type}] created {result['path']}")
    return ApiSuccess(data=result, duration_ms=duration_ms())


@app.post("/api/tasks/{task_id}/close", response_model=Union[ApiSuccess, ApiError])
def close_task(task_id: str, req: CloseTaskRequest):
    """Завершить задачу: выставить status: done, date_completed: сегодня, hours: N.
    Сохраняет остальной frontmatter и тело файла. После — перегенерирует data.json."""
    start_t = time.time()
    # Защита от path traversal: блокируем разделители путей и обход директорий.
    # Кириллица и пробелы разрешены (имена файлов вроде «восстановление сайта.md»).
    if "/" in task_id or "\\" in task_id or ".." in task_id or "\x00" in task_id:
        return ApiError(code="BAD_TASK_ID", message="Недопустимый идентификатор задачи",
                       duration_ms=int((time.time() - start_t) * 1000))

    task_path = VAULT_PATH / "30_Tasks" / f"{task_id}.md"
    if not task_path.exists():
        logger.error(f"[close_task] task={task_id} not found")
        return ApiError(code="TASK_NOT_FOUND", message=f"Задача {task_id} не найдена",
                       duration_ms=int((time.time() - start_t) * 1000))

    try:
        content = task_path.read_text(encoding="utf-8")
        today = datetime.date.today().isoformat()
        hours_val = f"{float(req.hours):g}"

        # Извлечь frontmatter между первой парой ---
        fm_match = re.match(r'^(---\n)(.*?)(\n---\n)', content, re.DOTALL)
        if fm_match:
            fm = fm_match.group(2)
            fm = _set_frontmatter_field(fm, "status", "done")
            fm = _set_frontmatter_field(fm, "date_completed", today)
            fm = _set_frontmatter_field(fm, "hours", hours_val)
            new_content = fm_match.group(1) + fm + fm_match.group(3) + content[fm_match.end():]
        else:
            # Нет frontmatter — создаём минимальный
            new_fm = f"---\nstatus: done\ndate_completed: {today}\nhours: {hours_val}\n---\n\n"
            new_content = new_fm + content

        task_path.write_text(new_content, encoding="utf-8")
        logger.info(f"[close_task] task={task_id} closed hours={hours_val} date={today}")
    except Exception as e:
        logger.error(f"[close_task] task={task_id} write failed: {e}")
        return ApiError(code="WRITE_ERROR", message=f"Ошибка записи: {e}",
                       duration_ms=int((time.time() - start_t) * 1000))

    # Перегенерируем data.json, чтобы задача исчезла из матрицы Эйзенхауэра
    try:
        import sys as _sys
        _sys.path.append(os.path.join(BASE_DIR, "scripts"))
        import extract_dashboard_data as _ext
        import importlib as _il
        _il.reload(_ext)
        data = _ext.build_dashboard_data()
        tmp_path = DATA_FILE + ".tmp"
        with safe_open_w(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        os.replace(tmp_path, DATA_FILE)
    except Exception as e:
        logger.error(f"[close_task] data.json rebuild failed: {e}")

    return ApiSuccess(data={"message": f"Задача завершена, списано {hours_val} ч.",
                            "hours": float(hours_val), "date_completed": today},
                      duration_ms=int((time.time() - start_t) * 1000))


# ---------- PD Safe (сейф персональных данных) ----------
# Прокси на демон pd_lockd (127.0.0.1:8765): пароль живёт только в демоне,
# через API ходят лишь команды status/lock/unlock. Демон не запущен → daemon: False.
PD_LOCKD = "http://127.0.0.1:8765"


@app.get("/api/pd_safe/status")
def pd_safe_status():
    try:
        r = requests.get(f"{PD_LOCKD}/status", timeout=3)
        return r.json()
    except Exception:
        return {"daemon": False, "open": None}


@app.post("/api/pd_safe/{action}")
def pd_safe_action(action: str):
    if action not in ("lock", "unlock"):
        raise HTTPException(status_code=404, detail="Доступны только lock/unlock")
    try:
        r = requests.post(f"{PD_LOCKD}/{action}", timeout=60)
        return r.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail="Демон сейфа ПД не запущен (нет пароля в памяти)")


# ---------- Почтовый клиент (вкладка «Почта» в дашборде) ----------
# Индекс писем строится из 20_Inbox + 20_Outbox; связи (счета/акты/задачи/
# сессии/тред) вычисляются на лету по клиенту и тексту письма.
import sys as _sys
import threading as _threading

MAIL_INBOX = BASE_DIR / "20_Inbox"
MAIL_OUTBOX = BASE_DIR / "20_Outbox"
MAIL_ATTACH_ROOT = MAIL_INBOX / "attachments"
MAIL_CLIENTS_DIR = BASE_DIR / "10_Clients"
MAIL_INVOICES_DIR = BASE_DIR / "30_Invoices"
MAIL_TASKS_DIR = BASE_DIR / "30_Tasks"
MAIL_TMP_DIR = BASE_DIR / "tmp-mail-send"

_mail_cache = {"sig": None, "messages": [], "invoices": [], "tasks": [], "clients": {}}
_mail_lock = _threading.Lock()


def _mail_parse_doc(path: Path):
    """(frontmatter dict, body) из md-файла; вложения собираются и из YAML-списка."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return {}, ""
    fm, body = {}, text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end > 0:
            block = text[4:end]
            body = text[end + 4:].lstrip("\n")
            for line in block.splitlines():
                m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$", line)
                if m and not m.group(2).strip().startswith("-"):
                    val = m.group(2).strip()
                    if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                        val = val[1:-1]
                    fm[m.group(1)] = val
            fm["_attachments"] = [m.group(1).strip()
                                  for m in (re.match(r"^\s*-\s+(.+)$", ln) for ln in block.splitlines()) if m]
    return fm, body



def _mail_preview(body: str):
    """Аккуратное превью письма: без markdown-заголовков и служебных строк."""
    lines = []
    for ln in (body or "").splitlines():
        s = ln.strip()
        if not s or s.startswith(("#", "**", "---", "```")) or s.startswith("- **"):
            continue
        if re.match(r"^- 20_Inbox/", s):
            continue
        lines.append(s)
    return re.sub(r"\s+", " ", " ".join(lines))[:200]

def _mail_norm_client(val: str):
    return re.sub(r"^\[\[|\]\]$", "", (val or "").strip())


def _mail_thread_key(subject: str):
    s = re.sub(r"^(?:(?:re|fwd?|ответ|пересыл)\s*:\s*)+", "", (subject or "").strip(), flags=re.I)
    return re.sub(r"\s+", " ", s).strip().lower()[:64]


def _mail_parse_dt(val):
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime((val or "").strip()[:len("YYYY-MM-DD HH:MM:SS")], fmt)
        except Exception:
            continue
    return None


def _mail_dir_sig():
    parts = []
    for d in (MAIL_INBOX, MAIL_OUTBOX, MAIL_INVOICES_DIR, MAIL_TASKS_DIR, MAIL_CLIENTS_DIR):
        try:
            parts.append(f"{d.name}:{int(os.path.getmtime(d))}")
        except Exception:
            parts.append(f"{d.name}:0")
    return "|".join(parts)


def _mail_scan_all():
    messages = []
    for d, direction in ((MAIL_INBOX, "in"), (MAIL_OUTBOX, "out")):
        for p in sorted(d.glob("*.md")):
            name = p.name
            if direction == "out" and not name.startswith("out_email_"):
                continue  # в Outbox лежат и MAX/TG — берём только email
            fm, body = _mail_parse_doc(p)
            if fm.get("channel", "email") not in ("email",) and direction == "out":
                continue
            if direction == "in" and fm.get("source", "email") != "email":
                continue
            subj = fm.get("subject", "")
            messages.append({
                "file": f"{d.name}/{name}",
                "direction": direction,
                "mailbox": fm.get("mailbox", ""),
                "from": fm.get("sender", "") if direction == "in" else "",
                "to": fm.get("to", ""),
                "client": _mail_norm_client(fm.get("client", "")),
                "unmatched": fm.get("unmatched", "") == "true",
                "subject": subj,
                "date": fm.get("date", ""),
                "dt": _mail_parse_dt(fm.get("date", "")),
                "message_id": fm.get("message_id", ""),
                "attachments": fm.get("_attachments", []),
                "body": body,
                "preview": _mail_preview(body),
                "thread_key": _mail_thread_key(subj),
            })

    invoices = []
    for p in sorted(MAIL_INVOICES_DIR.glob("*.md")):
        fm, _ = _mail_parse_doc(p)
        if not fm.get("invoice_number"):
            continue
        invoices.append({
            "file": f"30_Invoices/{p.name}",
            "number": fm.get("invoice_number", ""),
            "client": _mail_norm_client(fm.get("client", "")),
            "date": fm.get("invoice_date", ""),
            "dt": _mail_parse_dt(fm.get("invoice_date", "")),
            "amount": fm.get("amount", ""),
            "status": fm.get("status", ""),
            "act_status": fm.get("act_status", ""),
            "act_pdf": fm.get("act_pdf", ""),
            "invoice_pdf": fm.get("invoice_pdf", ""),
            "period": fm.get("period", ""),
        })

    tasks = []
    for p in sorted(MAIL_TASKS_DIR.glob("*.md")):
        fm, body = _mail_parse_doc(p)
        title = ""
        m = re.search(r"^#\s+(.+)$", body, re.M)
        if m:
            title = m.group(1).strip()
        tasks.append({
            "file": f"30_Tasks/{p.name}",
            "title": title or p.stem,
            "client": _mail_norm_client(fm.get("client", "")),
            "created": fm.get("created", ""),
            "dt": _mail_parse_dt(fm.get("created", "")),
            "completed": fm.get("date_completed", ""),
            "status": fm.get("status", ""),
        })

    clients = {}
    for p in sorted(MAIL_CLIENTS_DIR.glob("*.md")):
        fm, body = _mail_parse_doc(p)
        sessions = re.findall(r"sess_[0-9a-f\-]{8,}", body + "\n" + str(fm.get("project_sessions", "")))
        clients[p.stem] = {"file": f"10_Clients/{p.name}", "sessions": sorted(set(sessions))}
    return messages, invoices, tasks, clients


def _mail_ensure_index():
    sig = _mail_dir_sig()
    with _mail_lock:
        if _mail_cache["sig"] == sig and _mail_cache["messages"]:
            return _mail_cache
        messages, invoices, tasks, clients = _mail_scan_all()
        messages.sort(key=lambda m: m["dt"] or datetime.datetime.min, reverse=True)
        _mail_cache.update({"sig": sig, "messages": messages, "invoices": invoices,
                            "tasks": tasks, "clients": clients})
    return _mail_cache


@app.get("/api/mail/mailboxes")
def mail_mailboxes():
    _sys.path.insert(0, str(Path(__file__).parent))
    from mail_utils import load_mailboxes
    boxes = [{"id": m["id"], "email": m["email"], "name": m.get("name", m["email"]),
              "default": bool(m.get("default")), "active": bool(m.get("active", True))}
             for m in load_mailboxes(active_only=False)]
    return ApiSuccess(data={"mailboxes": boxes}, duration_ms=0)


@app.get("/api/mail/messages")
def mail_messages(direction: str = None, mailbox: str = None, client: str = None,
                  q: str = None, limit: int = 300, offset: int = 0):
    idx = _mail_ensure_index()
    out = []
    qn = (q or "").strip().lower()
    for m in idx["messages"]:
        if direction and m["direction"] != direction:
            continue
        if mailbox and m["mailbox"] != mailbox:
            continue
        if client and m["client"] != client:
            continue
        if qn and qn not in (m["subject"].lower() + " " + m["body"].lower()
                             + " " + m["from"].lower() + " " + m["to"].lower()):
            continue
        out.append({k: v for k, v in m.items() if k not in ("body", "dt")})
    total = len(out)
    return ApiSuccess(data={"total": total, "messages": out[offset:offset + limit]}, duration_ms=0)


def _mail_letter_links(letter, idx):
    """Связи письма: клиент, счета/акты, задачи, сессии, тред, упомянутые счета."""
    links = {"client": None, "card": None, "sessions": [], "invoices": [],
             "mentioned_invoices": [], "tasks": [], "thread": []}
    cname = letter["client"]
    if cname:
        links["client"] = cname
        card = idx["clients"].get(cname)
        if not card:  # fuzzy: имя файла начинается с имени клиента
            for stem, c in idx["clients"].items():
                if stem.startswith(cname) or cname.startswith(stem):
                    card = c
                    break
        if card:
            links["card"] = card["file"]
            links["sessions"] = card["sessions"]

        ldt = letter.get("dt")
        invs = [i for i in idx["invoices"] if i["client"] == cname]
        if ldt:
            invs.sort(key=lambda i: abs((i["dt"] or datetime.datetime.min - ldt)
                                        .total_seconds()) if i["dt"] else 9e9)
        else:
            invs.sort(key=lambda i: i["dt"] or datetime.datetime.min, reverse=True)
        links["invoices"] = invs[:12]

        tks = [t for t in idx["tasks"] if t["client"] == cname]
        if ldt:
            tks.sort(key=lambda t: abs((t["dt"] or datetime.datetime.min - ldt)
                                       .total_seconds()) if t["dt"] else 9e9)
        links["tasks"] = tks[:15]

    nums = set(re.findall(r"B24-\d+", letter["subject"] + "\n" + letter["body"]))
    if nums:
        links["mentioned_invoices"] = [i for i in idx["invoices"] if i["number"] in nums][:8]

    links["thread"] = [{k: m[k] for k in ("file", "direction", "subject", "date", "from", "to")}
                       for m in idx["messages"]
                       if m["thread_key"] and m["thread_key"] == letter["thread_key"]
                       and m["file"] != letter["file"]][:30]
    return links


@app.get("/api/mail/message")
def mail_message(file: str):
    safe = os.path.realpath(str(BASE_DIR / file))
    base = os.path.realpath(str(BASE_DIR))
    if os.path.commonpath([base, safe]) != base or not safe.endswith(".md"):
        raise HTTPException(status_code=400, detail="недопустимый путь")
    if os.path.dirname(safe) not in (str(MAIL_INBOX), str(MAIL_OUTBOX)):
        raise HTTPException(status_code=400, detail="письма лежат в 20_Inbox/20_Outbox")
    if not os.path.isfile(safe):
        raise HTTPException(status_code=404, detail="письмо не найдено")

    idx = _mail_ensure_index()
    rel = str(Path(file).as_posix())
    letter = next((m for m in idx["messages"] if m["file"] == rel), None)
    if not letter:
        letter = {"file": rel, "direction": "out" if rel.startswith("20_Outbox") else "in",
                  "mailbox": "", "from": "", "to": "", "client": "", "unmatched": False,
                  "subject": "", "date": "", "dt": None, "message_id": "",
                  "attachments": [], "body": "", "thread_key": ""}
        fm, body = _mail_parse_doc(Path(safe))
        letter.update({"from": fm.get("sender", ""), "to": fm.get("to", ""),
                       "client": _mail_norm_client(fm.get("client", "")),
                       "subject": fm.get("subject", ""), "date": fm.get("date", ""),
                       "message_id": fm.get("message_id", ""),
                       "attachments": fm.get("_attachments", []), "body": body})
    letter = dict(letter)
    letter.pop("dt", None)
    letter["attachments"] = [{
        "name": os.path.basename(a),
        "url": f"/api/mail/attachment?path={a.replace(' ', '%20')}",
        "path": a,
    } for a in letter["attachments"]]
    return ApiSuccess(data={"letter": letter, "links": _mail_letter_links(letter, idx)}, duration_ms=0)


@app.get("/api/mail/attachment")
def mail_attachment(path: str):
    rp = os.path.realpath(str(BASE_DIR / path))
    att_root = os.path.realpath(str(MAIL_ATTACH_ROOT))
    if os.path.commonpath([att_root, rp]) != att_root or not os.path.isfile(rp):
        raise HTTPException(status_code=404, detail="вложение не найдено")
    return FileResponse(rp, filename=os.path.basename(rp))


class MailSendPayload(BaseModel):
    to: str
    subject: str
    text: str
    mailbox: Optional[str] = None
    reply_to: Optional[str] = None          # Message-ID; если пусто и дан reply_file — из его fm
    reply_file: Optional[str] = None        # письмо, на которое отвечаем (file в индексе)


@app.post("/api/mail/send")
async def mail_send(payload: MailSendPayload):
    start_t = time.time()
    if not re.match(r"[^@\s]+@[^@\s]+\.[^@\s]+", payload.to.strip()):
        raise HTTPException(status_code=400, detail="некорректный адрес получателя")
    reply_to = (payload.reply_to or "").strip()
    if not reply_to and payload.reply_file:
        rf = os.path.realpath(str(BASE_DIR / payload.reply_file))
        if os.path.commonpath([os.path.realpath(str(BASE_DIR)), rf]) == os.path.realpath(str(BASE_DIR)):
            fm, _ = _mail_parse_doc(Path(rf))
            reply_to = fm.get("message_id", "").strip().strip('"')
    text = payload.text.strip()
    if text and "Automata CRM assist" not in text:
        text += "\n\n🤖 Automata CRM assist · ИИ-ассистент Евгения"

    MAIL_TMP_DIR.mkdir(exist_ok=True)
    tf = MAIL_TMP_DIR / f"web_{int(time.time() * 1000)}.txt"
    try:
        tf.write_text(text, encoding="utf-8")
        cmd = [ "send_email.py", "--to", payload.to.strip(), "--subject", payload.subject.strip(),
                "--text-file", str(tf)]
        if payload.mailbox:
            cmd += ["--mailbox", payload.mailbox]
        if reply_to:
            cmd += ["--reply-to", reply_to]
        venv_py = str(BASE_DIR / "venv" / "bin" / "python3")
        interpreter = venv_py if os.path.exists(venv_py) else "python3"
        script = str(BASE_DIR / "scripts" / "send_email.py")
        proc = await asyncio.create_subprocess_exec(
            interpreter, script, *cmd[1:], stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, cwd=str(BASE_DIR))
        stdout, stderr = await proc.communicate()
        out = (stdout or b"").decode().strip()
        err = (stderr or b"").decode().strip()
        if proc.returncode != 0:
            logger.error(f"[mail/send] rc={proc.returncode} err={err[:200]}")
            raise HTTPException(status_code=502, detail=f"отправка не удалась: {(err or out)[:300]}")
        _mail_ensure_index()
        return ApiSuccess(data={"message": out}, duration_ms=int((time.time() - start_t) * 1000))
    finally:
        try:
            tf.unlink(missing_ok=True)
        except Exception:
            pass
