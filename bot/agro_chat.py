"""Colloquial Q&A for agronomists. Answers a free-text question grounded in the
field's CropWise data (passed in as context) + general agronomy knowledge, via
YandexGPT (in-RU, same key as parse_op/translate). Returns None on failure so the
caller can fall back gracefully.
"""
import asyncio

import requests

from bot.config import settings

_ENDPOINT = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"

_SYS = (
    "Ты — помощник агронома хозяйства «New Grain Co» (Центрально-Чернозёмный регион). "
    "Отвечай кратко, по-деловому и по-русски, как коллега в поле — без воды. "
    "Если ниже есть блок «ДАННЫЕ ПО ПОЛЮ» (это реальные операции и показатели из CropWise) — "
    "опирайся на него и НЕ придумывай операции, которых там нет; называй даты, препараты и "
    "нормы как в данных. Если данных по полю нет или вопрос общий — отвечай из общих "
    "агрономических знаний; по препаратам ориентируйся на Госкаталог пестицидов, не "
    "пересказывай фирменные атласы. Если чего-то не знаешь — честно скажи."
)


async def answer(question: str, context: str | None = None) -> str | None:
    if not (settings.yc_api_key and settings.yc_folder_id):
        return None
    user = (f"ДАННЫЕ ПО ПОЛЮ:\n{context}\n\nВОПРОС: {question}"
            if context else f"ВОПРОС: {question}")
    body = {
        "modelUri": f"gpt://{settings.yc_folder_id}/{settings.yc_translate_model}",
        "completionOptions": {"stream": False, "temperature": 0.3, "maxTokens": 700},
        "messages": [{"role": "system", "text": _SYS}, {"role": "user", "text": user}],
    }

    def _call() -> str:
        r = requests.post(_ENDPOINT,
                          headers={"Authorization": f"Api-Key {settings.yc_api_key}"},
                          json=body, timeout=45)
        r.raise_for_status()
        return r.json()["result"]["alternatives"][0]["message"]["text"].strip()

    try:
        return await asyncio.to_thread(_call)
    except Exception:
        return None
