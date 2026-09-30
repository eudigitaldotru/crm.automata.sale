"""TTS для голосовой голограммы Джарвиса (дашборд).

Провайдеры по приоритету:
  1. ElevenLabs  — если в env есть ELEVENLABS_API_KEY (голос: ELEVENLABS_VOICE_ID)
  2. edge-tts    — бесплатный, без ключей (голос: EDGE_TTS_VOICE, по умолчанию ru-RU-DariyaNeural)
Если оба недоступны — эндпоинт вернёт ошибку, фронт фолбэкнет на браузерный синтез.

Кэш: scripts/.tts_cache/<sha1>.mp3 — ключ = провайдер|голос|текст.
"""

import asyncio
import hashlib
import os
from pathlib import Path

CACHE_DIR = Path(__file__).parent / ".tts_cache"
CACHE_DIR.mkdir(exist_ok=True)

TTS_TEXT_LIMIT = 600

EDGE_VOICE = os.getenv("EDGE_TTS_VOICE", "ru-RU-SvetlanaNeural")
ELEVEN_VOICE = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")  # Rachel
ELEVEN_MODEL = os.getenv("ELEVENLABS_MODEL", "eleven_multilingual_v2")
ELEVEN_URL = "https://api.elevenlabs.io/v1/text-to-speech/" + ELEVEN_VOICE


def _cache_path(text: str, provider: str, voice: str) -> Path:
    key = hashlib.sha1(f"{provider}|{voice}|{text}".encode("utf-8")).hexdigest()
    return CACHE_DIR / f"{key}.mp3"


def _clean(text: str) -> str:
    return " ".join((text or "").split())[:TTS_TEXT_LIMIT]


async def _synth_eleven(text: str) -> bytes:
    """Синхронный requests в отдельном потоке (asyncio.to_thread)."""
    import requests

    key = os.getenv("ELEVENLABS_API_KEY", "")
    if not key:
        raise RuntimeError("ELEVENLABS_API_KEY не задан")

    def _call() -> bytes:
        r = requests.post(
            ELEVEN_URL,
            headers={"xi-api-key": key, "Content-Type": "application/json"},
            json={"text": text, "model_id": ELEVEN_MODEL},
            timeout=15,
        )
        r.raise_for_status()
        return r.content

    return await asyncio.to_thread(_call)


async def _synth_edge(text: str) -> bytes:
    import edge_tts

    mp3 = bytearray()
    comm = edge_tts.Communicate(text, EDGE_VOICE)
    async for chunk in comm.stream():
        if chunk["type"] == "audio":
            mp3.extend(chunk["data"])
    if not mp3:
        raise RuntimeError("edge-tts вернул пустой поток")
    return bytes(mp3)


async def synth(text: str):
    """Возвращает (bytes, content_type). Кэширует результат."""
    text = _clean(text)
    if not text:
        raise ValueError("пустой текст")

    providers = []
    if os.getenv("ELEVENLABS_API_KEY"):
        providers.append(("elevenlabs", ELEVEN_VOICE, _synth_eleven))
    providers.append(("edge-tts", EDGE_VOICE, _synth_edge))

    last_err = None
    for name, voice, fn in providers:
        cache = _cache_path(text, name, voice)
        if cache.exists() and cache.stat().st_size > 0:
            return cache.read_bytes(), "audio/mpeg"
        try:
            audio = await fn(text)
            cache.write_bytes(audio)
            return audio, "audio/mpeg"
        except Exception as e:  # следующий провайдер
            last_err = e
            continue

    raise RuntimeError(f"все TTS-провайдеры недоступны: {last_err}")
