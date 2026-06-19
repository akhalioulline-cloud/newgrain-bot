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
from datetime import date

import requests

from bot.config import settings

_ENDPOINT = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"

_SYS = (
    "Ты помощник агронома. Извлеки из заметки об операции на поле структуру и верни "
    "ТОЛЬКО JSON, без пояснений и без markdown. Ключи JSON:\n"
    'fields — СПИСОК всех полей из заметки, например ["262","252","251"] или ["119"] '
    'или ["121/140"]; если поле одно — список из одного элемента; если не указано — []\n'
    'field — первое поле из fields для совместимости (например "119"), иначе null\n'
    "category — одно из: tillage (обработка почвы), sowing (сев/посев), "
    "fertilizer (внесение удобрений), protection (опрыскивание/гербицид/фунгицид/"
    "инсектицид/СЗР), harvest (уборка урожая), other\n"
    'operation — короткое название операции по-русски (например "опрыскивание")\n'
    "product — торговое название препарата / семян / удобрения, иначе null\n"
    'dose — норма расхода с единицей (например "1.5 л/га"), иначе null\n'
    "area_ha — площадь в гектарах числом, иначе null\n"
    "target — против чего обработка (сорняки / болезнь / вредитель), иначе null\n"
    "driver — механизатор/водитель как в заметке: фамилия С ИМЕНЕМ и ОТЧЕСТВОМ или "
    'инициалами, если они указаны (например "Шапаренко Сергей Петрович" или "Яровой В.Н."), '
    "иначе только фамилия; иначе null. Имя и отчество важны — есть однофамильцы.\n"
    'machine — техника с номером, если указана (например "КамАЗ 286" или '
    '"самоходка 6448"), иначе null\n'
    "Пример логистики: «17 июня Двулучанский на камазе 286 подвозил воду» → "
    'driver="Двулучанский", machine="КамАЗ 286", operation="подвоз воды", '
    "category=other, fields=[] (поля нет — машина возит на много полей сразу).\n"
    'date — "today", "yesterday" или дата в формате ГГГГ-ММ-ДД (по умолчанию today). '
    "Если в заметке указан день и месяц без года (например «17 июня») — используй "
    "ТЕКУЩИЙ год.\n"
    "Заметка может содержать ошибки распознавания речи — исправь очевидные. "
    "Отвечай только JSON-объектом."
)


def _system_text() -> str:
    return _SYS + f"\nСегодня {date.today().isoformat()}."


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
        "completionOptions": {"stream": False, "temperature": 0, "maxTokens": 500},
        "messages": [
            {"role": "system", "text": _system_text()},
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
