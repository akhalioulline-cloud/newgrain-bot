"""Colloquial Q&A for agronomists. Answers a free-text question grounded in the
field's CropWise data (passed in as context) + general agronomy knowledge, via
YandexGPT (in-RU, same key as parse_op/translate). Returns None on failure so the
caller can fall back gracefully.
"""
import asyncio

import requests

from bot.config import settings

_ENDPOINT = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"

_BOT_GUIDE = (
    "СПРАВКА ПО БОТУ (используй, если спрашивают, КАК пользоваться ботом или как делать фото):\n"
    "• Записать обработку: напишите или наговорите голосом, например «опрыскал поле 119 "
    "Корсаром 1.5 л/га от сорняков». Бот сам определит поле, препарат, норму и дату; чего не "
    "хватит — переспросит; покажет подтверждение — нажмите ✓. Запись уйдёт в историю поля и в CropWise.\n"
    "• Сфотографировать сорняк/болезнь/вредителя: отправьте фото в бот, выберите поле, "
    "категорию, затем вид (или «Другой» — бот подскажет по фото). Можно добавить комментарий "
    "текстом или голосом.\n"
    "• Как правильно фотографировать: дневной свет, чёткий фокус, без смазывания; снимите два "
    "кадра — весь сорняк целиком и крупный план листа/соцветия; растение в центре кадра; "
    "не снимайте против солнца.\n"
    "• Узнать про поле: «поле 119» (или /field 119) — сводка по обработкам, культуре, NDVI, "
    "погоде. Или просто спросите словами.\n"
    "• История снимков: /history. Статистика за неделю: /stats. Ваши поля: /fields. "
    "Что нового в боте: /announce.\n"
    "• Текстовые команды и вопросы работают в личном чате с ботом."
)

_SYS = (
    "Ты — помощник агронома хозяйства «New Grain Co» (Центрально-Чернозёмный регион). "
    "Отвечай кратко, по-деловому и по-русски, как коллега в поле — без воды. "
    "Если ниже есть блок «ДАННЫЕ ПО ПОЛЮ» (это реальные операции и показатели из CropWise) — "
    "опирайся на него и НЕ придумывай операции, которых там нет; называй даты, препараты и "
    "нормы как в данных. Если спрашивают, как пользоваться ботом или как фотографировать — "
    "отвечай простыми словами по справке ниже. Если данных по полю нет или вопрос общий "
    "агрономический — отвечай из общих знаний; по препаратам ориентируйся на Госкаталог "
    "пестицидов, не пересказывай фирменные атласы. "
    "Если вопрос НЕ про поля и обработки хозяйства, не про агрономию и не про работу с "
    "ботом — или непонятен — не выдумывай ответ: вежливо скажи, что ты помощник агронома, "
    "и подскажи, с чем можешь помочь (поля и обработки, агрономия, как пользоваться ботом). "
    "Если чего-то не знаешь — честно скажи.\n\n"
    + _BOT_GUIDE
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
