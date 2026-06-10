"""Voice-note transcription via a local faster-whisper model.

Self-contained: the model runs inside this container, audio never leaves the
server, and there's no per-use cost or external API. The model is downloaded
once on first use (cached under HOME/.cache) and then kept in memory.
"""

import asyncio
import io
import logging
import threading

from bot.config import settings

logger = logging.getLogger("bot.transcribe")

_model = None
_model_lock = threading.Lock()


def _get_model():
    """Load the Whisper model once, lazily. Guarded so two concurrent voice
    notes don't both trigger a (slow) load."""
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                from faster_whisper import WhisperModel

                logger.info("Loading Whisper model %r (first call may download it)…",
                            settings.whisper_model)
                # int8 keeps CPU memory/latency low; fine for short field notes.
                _model = WhisperModel(settings.whisper_model, device="cpu", compute_type="int8")
    return _model


def _transcribe_sync(audio: bytes) -> str:
    model = _get_model()
    segments, _info = model.transcribe(io.BytesIO(audio), language="ru")
    return " ".join(segment.text.strip() for segment in segments).strip()


async def transcribe(audio: bytes) -> str:
    """Transcribe Russian speech from raw audio bytes (ogg/opus). Returns the
    recognized text, or an empty string if nothing could be made out."""
    return await asyncio.to_thread(_transcribe_sync, audio)


def _translate_sync(audio: bytes) -> str:
    model = _get_model()
    # task="translate" renders the (Russian) speech directly into English.
    segments, _info = model.transcribe(io.BytesIO(audio), language="ru", task="translate")
    return " ".join(segment.text.strip() for segment in segments).strip()


async def translate_en(audio: bytes) -> str:
    """English translation of the voice note (Whisper translate task). Best for
    the descriptive gist; weed/disease names may render loosely, so the
    reference sheet also scans the Russian transcript against the species
    dictionary for an exact match."""
    return await asyncio.to_thread(_translate_sync, audio)
