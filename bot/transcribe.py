"""Voice-note transcription via Yandex SpeechKit (cloud, RU).

Migrated from local faster-whisper (10 Jun 2026): SpeechKit transcribes Russian
at least as well — better on weed names ("Чина клубненосная" exact, vs Whisper's
garbled "Чина клубня носная") — frees the RAM-tight VM of the ~0.5 GB model, and
keeps everything on one provider/key (Yandex Cloud, RU). Audio goes to Yandex
Cloud, the same place the photos already live.

Uses the short-audio sync REST API (≤30 s / ≤1 MB), which covers normal field
notes. Telegram voice is OGG/Opus, which SpeechKit accepts directly. Returns ""
on empty/4xx (e.g. a too-long note) so the nightly backfill simply retries;
raises on 5xx so a real outage surfaces via the pipeline's alerting.
"""
import asyncio
import logging

import requests

from bot.config import settings

logger = logging.getLogger("bot.transcribe")

_STT_ENDPOINT = "https://stt.api.cloud.yandex.net/speech/v1/stt:recognize"


def _transcribe_sync(audio: bytes, fmt: str = "oggopus", rate: int | None = None) -> str:
    if not (settings.yc_api_key and settings.yc_folder_id):
        logger.warning("SpeechKit not configured (YC_API_KEY/YC_FOLDER_ID) — skipping.")
        return ""
    params = {"folderId": settings.yc_folder_id, "lang": "ru-RU", "format": fmt}
    if rate:
        params["sampleRateHertz"] = rate
    r = requests.post(
        _STT_ENDPOINT,
        headers={"Authorization": f"Api-Key {settings.yc_api_key}"},
        params=params,
        data=audio, timeout=30,
    )
    if r.status_code >= 500:
        logger.error("SpeechKit STT HTTP %s: %s", r.status_code, r.text[:200])
        r.raise_for_status()          # transient → surfaces via backfill/pipeline alert
    if r.status_code != 200:
        logger.error("SpeechKit STT HTTP %s: %s", r.status_code, r.text[:200])
        return ""                     # 4xx (e.g. audio >30 s/1 MB) → no retry-spam
    return (r.json().get("result") or "").strip()


async def transcribe(audio: bytes) -> str:
    """Transcribe Russian speech from Telegram voice bytes (OGG/Opus) via Yandex
    SpeechKit. Returns recognized text, or "" if nothing was made out.

    English translation is done separately from this Russian transcript by
    bot.translate_llm (YandexGPT, grounded in the species dictionary)."""
    return await asyncio.to_thread(_transcribe_sync, audio)


async def transcribe_lpcm(audio: bytes, rate: int = 16000) -> str:
    """Transcribe raw 16-bit mono LPCM (from the web mic via Web Audio API — browsers
    can't easily make OGG/Opus, but LPCM is trivial). Returns text or ""."""
    return await asyncio.to_thread(_transcribe_sync, audio, "lpcm", rate)
