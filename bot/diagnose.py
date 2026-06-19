"""Structured photo diagnosis + grounded advice — our answer to the «Андрей Тимофеевич»
photo flow, but grounded in data they don't have.

Two steps, both in-RU:
1. Vision (qwen) identifies the object on the photo → diagnosis + confidence + visible
   symptoms + a ranked differential + growth phase.
2. YandexGPT writes a STRUCTURED agronomic answer from that, grounded in our Госкаталог
   product registry (real registered products for the KNOWN crop, with producer tags) +
   CyberLeninka citations + the crop-safety rules — reusing bot.agro_chat's grounding.

We beat the competitor on grounding: when the field's crop is known we skip "какая
культура?" and name actual registered products for that crop. Low-confidence IDs stay
hedged (differential + "проверить в поле" + show the chief agronomist). Returns None on failure.
"""
import asyncio
import base64
import json
import logging
import re

import requests

from bot.agro_chat import _complete, _literature_grounding, _registry_grounding
from bot.config import settings

logger = logging.getLogger("bot.diagnose")

_QWEN_URL = "https://llm.api.cloud.yandex.net/v1/chat/completions"
_QWEN_MODEL = "qwen3.6-35b-a3b"

_VISION_SYS = (
    "На фото — растение или проблема с поля (Центрально-Чернозёмный регион, Белгородская "
    "область). Определи объект как агроном и верни ТОЛЬКО JSON без пояснений:\n"
    '{"diagnosis":"русское название","latin":"Latin name или null",'
    '"category":"сорняк|болезнь|вредитель|иное",'
    '"confidence":число 0-100,'
    '"phase":"фаза развития, напр. 2-4 листа, или null",'
    '"symptoms":["видимый признак", ...],'
    '"differential":[{"name":"альтернативный вариант","why":"чем отличается"}],'
    '"weed_class":"двудольный|злаковый|null"}\n'
    "Будь честен с уверенностью: всходы и злаковые трудно различить по фото — не завышай."
)

_DIAG_SYS = (
    "Ты — опытный агроном-консультант хозяйства «New Grain Co» (ЦЧР). По фото уже выполнено "
    "распознавание (блок РАСПОЗНАВАНИЕ). Составь ЧЁТКИЙ структурированный ответ агроному на "
    "русском, без воды, строго по разделам с такими заголовками (обычный текст, БЕЗ markdown-"
    "звёздочек):\n"
    "🔬 Диагноз: <название>. Если культура не указана — попроси подтвердить культуру (от неё "
    "зависит выбор препарата).\n"
    "📊 Уверенность: <число>%.\n"
    "👁 Что видно на фото: короткий список признаков из распознавания.\n"
    "❓ Что ещё это может быть: дифференциал (из differential), кратко чем отличается.\n"
    "🔎 Проверить в поле: 2–4 быстрые проверки.\n"
    "🛡 Меры борьбы: по пунктам — 1) механически/агротехнически, 2) химически.\n"
    "⏱ Лучшее время обработки: по фазе.\n\n"
    "ЖЁСТКИЕ ПРАВИЛА:\n"
    "• Безопасность культуры превыше всего: НЕ рекомендуй препараты, которые повредят саму "
    "культуру (глифосат — сплошной; на подсолнечнике/сое противодвудольные, трибенурон-метил, "
    "имидазолиноны — ТОЛЬКО на устойчивых гибридах Express/Clearfield, обязательно оговори это).\n"
    "• Если есть блок ЗАРЕГИСТРИРОВАННЫЕ ПРЕПАРАТЫ — называй препараты и нормы ТОЛЬКО из него "
    "(с пометкой производителя в скобках, если есть). Если блока нет (культура не названа) — дай "
    "рекомендации по ДЕЙСТВУЮЩИМ ВЕЩЕСТВАМ и попроси уточнить культуру для точного подбора.\n"
    "• Если есть блок НАУЧНЫЕ ИСТОЧНИКИ — можешь кратко сослаться (название + ссылка).\n"
    "• Если уверенность распознавания низкая (<60%) — честно скажи об этом, не настаивай на "
    "препаратах, предложи прислать более чёткое фото (целое растение + крупный план листа) или "
    "показать старшему агроному. Не выдумывай."
)


def _vision_sync(img: bytes) -> dict | None:
    if not (settings.yc_api_key and settings.yc_folder_id):
        return None
    body = {
        "model": f"gpt://{settings.yc_folder_id}/{_QWEN_MODEL}/latest",
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": _VISION_SYS},
            {"type": "image_url",
             "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(img).decode()}},
        ]}],
        "temperature": 0, "max_tokens": 2500,
    }
    try:
        r = requests.post(_QWEN_URL, headers={"Authorization": f"Api-Key {settings.yc_api_key}"},
                          json=body, timeout=90)
        if r.status_code != 200:
            logger.warning("diagnose vision HTTP %s", r.status_code)
            return None
        msg = r.json()["choices"][0]["message"]
        raw = msg.get("content") or msg.get("reasoning_content") or ""
        s = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
        m = re.search(r"\{.*\}", s, re.S)
        return json.loads(m.group(0)) if m else None
    except Exception:
        logger.exception("diagnose vision failed")
        return None


def _fmt_vision(vd: dict) -> str:
    parts = [f"diagnosis: {vd.get('diagnosis')}",
             f"latin: {vd.get('latin')}",
             f"category: {vd.get('category')}",
             f"confidence: {vd.get('confidence')}",
             f"phase: {vd.get('phase')}",
             f"symptoms: {'; '.join(vd.get('symptoms') or [])}",
             "differential: " + "; ".join(
                 f"{d.get('name')} ({d.get('why')})" for d in (vd.get("differential") or [])
                 if isinstance(d, dict))]
    return "\n".join(parts)


async def diagnose(img: bytes, question: str | None, crop: str | None,
                   field_name: str | None) -> str | None:
    """Structured diagnosis + grounded advice for a field photo. `crop`/`field_name` are
    the KNOWN field context (skip 'what crop?' when we have it). None on failure."""
    if not (settings.yc_api_key and settings.yc_folder_id):
        return None
    vd = await asyncio.to_thread(_vision_sync, img)
    if not vd or not vd.get("diagnosis"):
        return None
    target = str(vd["diagnosis"])
    # Reuse agro_chat grounding: build a synthetic «чем обработать <crop> от <target>» so the
    # registry grounding (products for crop+weed-class, producer tags, safety) kicks in.
    synth_q = (f"чем обработать {crop} от {target}" if crop else f"чем бороться с {target}")
    grounding = await _registry_grounding(synth_q)
    literature = await _literature_grounding(f"{target} {crop or ''}")

    ctx = [f"ВОПРОС АГРОНОМА: {question or 'что это и как с этим бороться?'}",
           (f"КУЛЬТУРА (из карточки поля {field_name}): {crop}" if crop
            else "КУЛЬТУРА: не указана — попроси подтвердить."),
           "РАСПОЗНАВАНИЕ (по фото):\n" + _fmt_vision(vd)]
    if grounding:
        ctx.append(grounding)
    if literature:
        ctx.append(literature)
    try:
        return await asyncio.to_thread(_complete, _DIAG_SYS, "\n\n".join(ctx), 1300, 0.4)
    except Exception:
        logger.exception("diagnose compose failed")
        return None
