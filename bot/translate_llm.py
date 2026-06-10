"""Translate Russian voice-note transcripts to English via YandexGPT.

Grounded in the weed_species dictionary so colloquial or speech-recognition-
garbled names map to the correct Latin name (e.g. "мышей зелёный" →
Setaria viridis). Whisper's translate task rendered weed names literally
("a mouse and a green one"); passing the dictionary to the LLM fixes that.

YandexGPT keeps the (short, text-only) call inside Yandex Cloud / RU, in line
with the project's data-residency posture. Returns "" if not configured or on
error — callers leave the EN field empty and the nightly backfill retries.
"""
import asyncio

import requests
from sqlalchemy import text

from bot.config import settings
from bot.db import engine

_ENDPOINT = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"

_SYS = (
    "Ты переводишь короткие голосовые заметки агронома с русского на английский. "
    "Заметка может содержать ошибки распознавания речи. Если в заметке упомянут вид "
    "из справочника ниже, используй его латинское название и общепринятое английское "
    "имя. Отвечай ТОЛЬКО переводом, без пояснений.\n\n"
    "Справочник видов (русское = латинское):\n"
)


async def _species_ref() -> str:
    async with engine.connect() as c:
        rows = (await c.execute(text(
            "SELECT latin_name, russian_name, common_aliases FROM weed_species"
        ))).mappings().all()
    out = []
    for r in rows:
        names = [r["russian_name"]] + (list(r["common_aliases"]) if r["common_aliases"] else [])
        out.append(", ".join(names) + " = " + r["latin_name"])
    return "\n".join(out)


async def translate_ru_to_en(ru_text: str) -> str:
    """Russian transcript → English (species-grounded). "" if disabled/failed."""
    ru_text = (ru_text or "").strip()
    if not ru_text or not (settings.yc_api_key and settings.yc_folder_id):
        return ""
    sysmsg = _SYS + await _species_ref()
    body = {
        "modelUri": f"gpt://{settings.yc_folder_id}/{settings.yc_translate_model}",
        "completionOptions": {"stream": False, "temperature": 0, "maxTokens": 300},
        "messages": [
            {"role": "system", "text": sysmsg},
            {"role": "user", "text": ru_text},
        ],
    }

    def _call() -> str:
        r = requests.post(
            _ENDPOINT,
            headers={"Authorization": f"Api-Key {settings.yc_api_key}"},
            json=body, timeout=30,
        )
        r.raise_for_status()
        return r.json()["result"]["alternatives"][0]["message"]["text"].strip()

    return await asyncio.to_thread(_call)
