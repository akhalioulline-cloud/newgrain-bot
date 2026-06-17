"""Suggest the top weed species from a photo, using the in-RU vision model
(qwen3.6-35b-a3b on Yandex AI Studio — Gemini is geo-blocked from the server).

Used ONLY as a fallback when the agronomist taps «Другой» (can't ID it): it offers
2–3 RANKED guesses to jog their memory. It NEVER auto-labels — the human always
picks. Off-the-shelf accuracy is ~37% top-1 (see the bake-off), so this is a hint,
not an answer. Returns [] on any error/timeout so the caller falls back to free text.
"""
import asyncio
import base64
import json
import logging
import re

import requests

from bot.config import settings

logger = logging.getLogger("bot.weed_suggest")

_URL = "https://llm.api.cloud.yandex.net/v1/chat/completions"
_MODEL = "qwen3.6-35b-a3b"


def _prompt(species) -> str:
    lst = "\n".join(f"- {s['russian_name']} ({s['latin_name']})" for s in species)
    return (
        "На фото — сорняк с поля (Центрально-Чернозёмный регион России). Назови ДО ТРЁХ "
        "наиболее вероятных видов, по возможности из списка ниже, начиная с самого "
        'вероятного. Ответь ТОЛЬКО JSON-массивом без пояснений: '
        '[{"ru":"русское название","latin":"Latin name"}]. \n\nСписок видов:\n' + lst
    )


def _parse(txt: str):
    s = re.sub(r"^```(?:json)?|```$", "", (txt or "").strip(), flags=re.M).strip()
    m = re.search(r"\[.*\]", s, re.S)
    if not m:
        return []
    try:
        return json.loads(m.group(0))
    except Exception:
        return []


def _call_sync(img: bytes, species) -> list:
    if not (settings.yc_api_key and settings.yc_folder_id):
        return []
    body = {
        "model": f"gpt://{settings.yc_folder_id}/{_MODEL}/latest",
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": _prompt(species)},
            {"type": "image_url",
             "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(img).decode()}},
        ]}],
        "temperature": 0, "max_tokens": 1500,
    }
    try:
        r = requests.post(_URL, headers={"Authorization": f"Api-Key {settings.yc_api_key}"},
                          json=body, timeout=60)
        if r.status_code != 200:
            logger.warning("weed-suggest HTTP %s", r.status_code)
            return []
        msg = r.json()["choices"][0]["message"]
        guesses = _parse(msg.get("content") or msg.get("reasoning_content") or "")
    except Exception:
        logger.exception("weed-suggest call failed")
        return []
    out = []
    for g in guesses:
        if isinstance(g, dict) and g.get("ru"):
            out.append({"ru": str(g["ru"]).strip(), "latin": str(g.get("latin") or "").strip()})
    return out[:3]


async def suggest_species(img: bytes, species) -> list:
    """Top ≤3 species guesses [{ru, latin}] for a photo; [] on any failure."""
    return await asyncio.to_thread(_call_sync, img, species)
