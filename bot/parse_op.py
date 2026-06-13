"""Parse a free-form / voice operation note into structured fields via YandexGPT.

The agronomist says «опрыскал 119 корсаром 1.5 л/га от сорняков» and we turn it
into {field, category, operation, product, dose, area_ha, target, date} so it can
land in field_treatments with no form-filling. Same YandexGPT path as
translate_llm (keeps the call inside Yandex Cloud / RU). Returns None if disabled
or unparseable — the handler then asks the agronomist to rephrase.
"""
import asyncio
import json
import re

import requests

from bot.config import settings

_ENDPOINT = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"

_SYS = (
    "Ты помощник агронома. Извлеки из заметки об операции на поле структуру и верни "
    "ТОЛЬКО JSON, без пояснений и без markdown. Ключи JSON:\n"
    'field — номер или название поля (например "119" или "121/140"), иначе null\n'
    "category — одно из: tillage (обработка почвы), sowing (сев/посев), "
    "fertilizer (внесение удобрений), protection (опрыскивание/гербицид/фунгицид/"
    "инсектицид/СЗР), other\n"
    'operation — короткое название операции по-русски (например "опрыскивание")\n'
    "product — торговое название препарата / семян / удобрения, иначе null\n"
    'dose — норма расхода с единицей (например "1.5 л/га"), иначе null\n'
    "area_ha — площадь в гектарах числом, иначе null\n"
    "target — против чего обработка (сорняки / болезнь / вредитель), иначе null\n"
    'date — "today", "yesterday" или дата в формате ГГГГ-ММ-ДД (по умолчанию today)\n'
    "Заметка может содержать ошибки распознавания речи — исправь очевидные. "
    "Отвечай только JSON-объектом."
)


def _clean(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"^```(?:json)?", "", s).strip()
    s = re.sub(r"```$", "", s).strip()
    return s


async def parse_operation(note: str) -> dict | None:
    note = (note or "").strip()
    if not note or not (settings.yc_api_key and settings.yc_folder_id):
        return None
    body = {
        "modelUri": f"gpt://{settings.yc_folder_id}/{settings.yc_translate_model}",
        "completionOptions": {"stream": False, "temperature": 0, "maxTokens": 400},
        "messages": [
            {"role": "system", "text": _SYS},
            {"role": "user", "text": note},
        ],
    }

    def _call() -> str:
        r = requests.post(
            _ENDPOINT,
            headers={"Authorization": f"Api-Key {settings.yc_api_key}"},
            json=body, timeout=30,
        )
        r.raise_for_status()
        return r.json()["result"]["alternatives"][0]["message"]["text"]

    try:
        raw = await asyncio.to_thread(_call)
        data = json.loads(_clean(raw))
        return data if isinstance(data, dict) else None
    except Exception:
        return None
