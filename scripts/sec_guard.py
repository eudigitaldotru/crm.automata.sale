#!/usr/bin/env python3
"""sec_guard.py — общий страж безопасности для скриптов AUTOMATA-CRM.

Единые точки для типовых операций, помечаемых статическими сканерами
(SSRF / path traversal):

- guard_path(path, root=BASE)    — канонизация + проверка «внутри root»
- guard_open(path, *a, **kw)     — open() только внутри vault
- guard_urlopen(url, timeout, context=None) — исходящие запросы только на
  публичные адреса (запрет private/loopback/link-local/metadata), без редиректов

Импорт: from sec_guard import guard_open, guard_urlopen, BASE
"""
import ipaddress
import os
import socket
import http.client  # сетевой слой только http.client
import json as _json
import time as _time
import datetime as _datetime
from urllib.parse import urlparse, urlencode, urljoin

BASE = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def guard_path(path, root=BASE):
    """Канонизирует путь и требует, чтобы он лежал внутри root (vault)."""
    rp = os.path.realpath(str(path))
    root = os.path.realpath(root)
    if os.path.commonpath([root, rp]) != root:
        raise ValueError(f"путь вне разрешённого корня: {rp}")
    return rp


def guard_open(path, *args, **kwargs):
    """open() с проверкой пути внутри vault (path traversal)."""
    return open(guard_path(path), *args, **kwargs)


def guard_external_url(url):
    """SSRF-гвард: только http(s), хост резолвится в публичный IP."""
    pu = urlparse(str(url))
    if pu.scheme not in ("http", "https") or not pu.hostname:
        raise ValueError(f"запрещённый URL: {str(url)[:80]}")
    try:
        infos = socket.getaddrinfo(pu.hostname, pu.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise ValueError(f"DNS не разрешил {pu.hostname}: {e}")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or str(ip) == "169.254.169.254"):
            raise ValueError(f"URL ведёт на внутренний адрес: {pu.hostname} -> {ip}")



def _hc_request(url, timeout=8, context=None, method="GET", headers=None, data=None, max_redirects=3):
    """Низкоуровневый запрос через http.client (без urllib-sinks).

    Каждый хоп (включая редиректы) прогоняется через SSRF-гвард.
    Возвращает (resp, elapsed_seconds): таймер — от начала запроса до заголовков ответа
    (аналог requests.Response.elapsed, нужен uptime_check для метрики «сайт тормозит»).
    """
    t0 = _time.perf_counter()
    for _ in range(max_redirects + 1):
        guard_external_url(url)  # редирект тоже может вести на private-адрес
        u = urlparse(url)
        host, port, path = u.hostname, u.port or (443 if u.scheme == "https" else 80), (u.path or "/") + (f"?{u.query}" if u.query else "")
        if u.scheme == "https":
            conn = http.client.HTTPSConnection(host, port, timeout=timeout, context=context)
        else:
            conn = http.client.HTTPConnection(host, port, timeout=timeout)
        conn.request(method, path, body=data, headers=dict(headers or {}))
        resp = conn.getresponse()
        if resp.status in (301, 302, 303, 307, 308) and resp.getheader("Location") and max_redirects > 0:
            url = urljoin(url, resp.getheader("Location"))
            # 303 — всегда GET; 301/302 при POST браузеры/requests тоже превращают в GET
            if method != "GET" and resp.status in (301, 302, 303):
                method, data = "GET", None
            resp.close()
            conn.close()
            continue
        resp._guard_conn = conn  # чтобы вызывающий мог закрыть соединение вместе с ответом
        return resp, _time.perf_counter() - t0
    raise ValueError("слишком много редиректов")


class GuardResponse:
    """requests-совместимая обёртка над http.client.HTTPResponse.

    До sec_guard вызовы шли через requests; после — часть скриптов осталась
    на requests-интерфейсе (status_code/text/json/elapsed), часть перешла
    на http.client (status/read). Поддерживаем оба, чтобы не править 15+ скриптов.
    """
    def __init__(self, resp, elapsed_s=0.0):
        self._resp = resp
        self._conn = getattr(resp, "_guard_conn", None)
        self._body = None
        self.status_code = resp.status
        self.ok = 200 <= resp.status < 400
        self.elapsed = _datetime.timedelta(seconds=elapsed_s)
        self.headers = dict(resp.getheaders())

    @property
    def status(self):
        return self._resp.status

    def _read_body(self):
        if self._body is None:
            self._body = self._resp.read()
            self.close()
        return self._body

    @property
    def content(self):
        return self._read_body()

    @property
    def text(self):
        return self._read_body().decode("utf-8", errors="replace")

    def json(self):
        return _json.loads(self._read_body())

    # делегаты http.client-интерфейса (hub_push и пр.)
    def read(self, *args, **kwargs):
        return self._resp.read(*args, **kwargs)

    def getheader(self, name, default=None):
        return self._resp.getheader(name, default)

    def getheaders(self):
        return self._resp.getheaders()

    def close(self):
        try:
            self._resp.close()
        finally:
            if self._conn is not None:
                self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _default_headers(headers):
    """UA по умолчанию — как у requests до sec_guard: часть сайтов режет пустых/чужих ботов."""
    h = dict(headers or {})
    if not any(k.lower() == "user-agent" for k in h):
        h["User-Agent"] = "python-requests/2.32.3"
    return h


def guard_urlopen(url_or_req, timeout=10, context=None):
    """Запрос с SSRF-гвардом через http.client; возвращает сырой HTTPResponse
    (file-like: with/resp.read()) — так его уже используют tg/max/bitrix-клиенты.

    ⚠️ Инцидент 29.09: Request с data= (POST) терял method и тело — уходил как GET,
    шлюз отвечал 405, а вызывающий код читал error-body как успех (счёт «улетал»
    в никуда). Теперь method и data пробрасываются явно.
    """
    url = getattr(url_or_req, "full_url", url_or_req)
    guard_external_url(url)
    _hdrs = dict(getattr(url_or_req, "headers", {}) or {})
    _data = getattr(url_or_req, "data", None)
    _method = getattr(url_or_req, "method", None) or ("POST" if _data is not None else "GET")
    resp, _elapsed = _hc_request(url, timeout=timeout, context=context,
                                 headers=_hdrs, data=_data, method=_method)
    return resp


def guard_requests_get(url, **kwargs):
    """HTTP GET с SSRF-гвардом; requests-совместимый ответ (status_code/text/json/elapsed)."""
    params = kwargs.get("params")
    if params:
        url = f"{url}{'&' if '?' in url else '?'}{urlencode(params)}"
    allow_redirects = kwargs.get("allow_redirects", True)
    guard_external_url(url)
    resp, elapsed = _hc_request(
        url,
        timeout=kwargs.get("timeout", 15),
        headers=_default_headers(kwargs.get("headers")),
        max_redirects=5 if allow_redirects else 0,
    )
    return GuardResponse(resp, elapsed)


def guard_requests_post(url, **kwargs):
    """HTTP POST с SSRF-гвардом; requests-совместимый ответ (status_code/json/text)."""
    guard_external_url(url)
    data = kwargs.get("json")
    headers = _default_headers(kwargs.get("headers"))
    if data is not None:
        headers.setdefault("Content-Type", "application/json")
    resp, elapsed = _hc_request(
        url,
        timeout=kwargs.get("timeout", 15),
        headers=headers,
        method="POST",
        data=_json.dumps(data).encode() if data is not None else None,
    )
    return GuardResponse(resp, elapsed)
