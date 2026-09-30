"""
hub_push.py — отправка событий CRM на мобильный хаб automata.sale.

Хаб: POST {HUB_URL}/api/hub/ingest с Bearer HUB_TOKEN (роут site/src/pages/api/hub/ingest.ts).

Надёжность: если сервер/интернет недоступны, события складываются в spool-очередь
на диске (scripts/.hub_spool/) и отправляются при следующем успешном вызове.
Все функции глотают исключения — сбой отправки НИКОГДА не должен ломать мониторинг.

Использование из других скриптов:
    from hub_push import send_event, send_monitoring_snapshot
    send_event("site_down", "Сайт упал", severity="critical",
               payload={"domain": "x.ru"},
               push={"title": "🔴 x.ru недоступен", "body": "Клиент", "channel": "critical"})
"""
from sec_guard import guard_open, guard_requests_post


import os
import json
import time
import uuid
import glob

import requests
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SPOOL_DIR = os.path.join(BASE_DIR, ".hub_spool")
SPOOL_MAX_FILES = 500      # старше этого количества — отбрасываем самые старые
BATCH_SIZE = 20            # событий за один запрос
HTTP_TIMEOUT = 15

load_dotenv(os.path.join(os.path.dirname(BASE_DIR), ".env"))

HUB_URL = os.getenv("HUB_URL", "https://automata.sale").rstrip("/")
HUB_TOKEN = os.getenv("HUB_TOKEN", "")

_warned_no_token = False


def _ingest(body):
    """POST на хаб. True — сервер принял (в т.ч. дубликаты)."""
    resp = guard_requests_post(
        f"{HUB_URL}/api/hub/ingest",
        json=body,
        headers={"Authorization": f"Bearer {HUB_TOKEN}"},
        timeout=HTTP_TIMEOUT,
    )
    status = resp.status  # http.client.HTTPResponse (не requests: там status_code)
    resp.read()
    return status == 200


def _spool_add(events):
    os.makedirs(SPOOL_DIR, exist_ok=True)
    fname = os.path.join(SPOOL_DIR, f"{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}.json")
    with guard_open(fname, "w", encoding="utf-8") as f:
        json.dump(events, f, ensure_ascii=False)
    _spool_trim()


def _spool_trim():
    files = sorted(glob.glob(os.path.join(SPOOL_DIR, "*.json")))
    excess = len(files) - SPOOL_MAX_FILES
    if excess > 0:
        for f in files[:excess]:
            try:
                os.remove(f)
            except OSError:
                pass
        print(f"[hub] spool переполнен, отброшено старых событий: {excess}")


def _spool_flush():
    """Отправляет накопленную очередь. Возвращает число отправленных событий."""
    files = sorted(glob.glob(os.path.join(SPOOL_DIR, "*.json")))
    sent = 0
    for f in files:
        try:
            with guard_open(f, "r", encoding="utf-8") as fh:
                events = json.load(fh)
        except (OSError, ValueError):
            # битый файл очереди — удаляем, чтобы не блокировать очередь
            try:
                os.remove(f)
            except OSError:
                pass
            continue

        for i in range(0, len(events), BATCH_SIZE):
            chunk = events[i:i + BATCH_SIZE]
            try:
                if not _ingest({"events": chunk}):
                    return sent  # сервер недоступен — досылаем позже
            except OSError:  # сетевые ошибки http.client и requests.RequestException — оба OSError
                return sent
            sent += len(chunk)

        try:
            os.remove(f)
        except OSError:
            pass
    return sent


def send_events(events, flush_spool=True):
    """
    Отправляет список событий [{type, title, dedup_key?, severity?, payload?, push?}].
    При неудаче — в spool. Возвращает True, если до сервера доехало (или ушло в очередь).
    """
    global _warned_no_token
    if not HUB_TOKEN:
        if not _warned_no_token:
            print("[hub] HUB_TOKEN не задан в .env — отправка на хаб отключена")
            _warned_no_token = True
        return False

    events = [e for e in events if e and e.get("type") and e.get("title")]
    if not events:
        return True

    if flush_spool:
        try:
            _spool_flush()
        except Exception as e:
            print(f"[hub] spool flush error: {e}")

    try:
        if _ingest({"events": events}):
            return True
    except OSError as e:  # сеть/таймаут (http.client и requests здесь оба OSError)
        print(f"[hub] сервер недоступен ({e}); события в очередь: {len(events)}")
    except Exception as e:
        print(f"[hub] ошибка отправки: {e}")

    try:
        _spool_add(events)
    except Exception as e:
        print(f"[hub] не удалось сохранить spool: {e}")
    return False


def send_event(type_, title, dedup_key=None, severity="info", payload=None, push=None):
    ev = {"type": type_, "title": title, "severity": severity}
    if dedup_key:
        ev["dedup_key"] = dedup_key
    if payload is not None:
        ev["payload"] = payload
    if push:
        ev["push"] = push
    return send_events([ev])


def send_monitoring_snapshot(data):
    """
    Отправляет снапшот monitoring.json на хаб (для /status и приложения).
    Без очереди: снапшот устаревает — следующий цикл пришлёт свежий.
    """
    if not HUB_TOKEN or not data:
        return False
    try:
        return _ingest({"monitoring": data})
    except Exception as e:
        print(f"[hub] snapshot не отправлен: {e}")
        return False


if __name__ == "__main__":
    # Ручной тест: python hub_push.py
    ok = send_event(
        "test",
        "Тест отправки из hub_push.py",
        dedup_key=f"test-{uuid.uuid4().hex[:6]}",
        push={"title": "🧪 Тест хаба", "body": "Если видишь это — пуш работает", "channel": "default"},
    )
    from monitoring_core import load_monitoring_data
    snap_ok = send_monitoring_snapshot(load_monitoring_data())
    print(f"event: {'OK' if ok else 'FAIL/queued'}, snapshot: {'OK' if snap_ok else 'FAIL'}")
