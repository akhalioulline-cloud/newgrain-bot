"""Field treatment-plan generator (Pilot v2 — the decision layer).

Turns a field's state — its CropWise history + recent scouting + the registered-product
catalog — into a structured, registered-only treatment plan that favours treating ONLY
what needs treating (vs the blanket spray). This is the product thesis made testable:
put a plan in front of an agronomist and compare it to what they actually sprayed.

Reuses the same grounded pieces as the assistant: field_card_text (data layer),
get_registered_products (Госкаталог), and YandexGPT via agro_chat._complete.
"""
import asyncio
import logging

from bot.agro_chat import _complete
from bot.config import settings
from bot.db import (
    field_card_text,
    get_field_observations,
    get_field_protection_baseline,
    get_registered_products,
    producer_label,
    resolve_field,
)

logger = logging.getLogger(__name__)

CAT_RU = {"weed": "сорняк", "disease": "болезнь", "pest": "вредитель",
          "scouting": "обследование", "treatment_result": "после обработки",
          "other": "прочее"}

_PLAN_SYS = (
    "Ты — опытный агроном-консультант хозяйства АО «НЗК» (ЦЧР). На основе ДАННЫХ ПО ПОЛЮ, "
    "ОБСЛЕДОВАНИЯ и списка ЗАРЕГИСТРИРОВАННЫХ препаратов составь ПЛАН РАБОТ по полю — обычным "
    "текстом, без markdown-звёздочек, по разделам с такими заголовками-значками:\n"
    "🗺 Состояние поля: культура, ориентировочная фаза, что показывают обследование и история — 1–3 фразы.\n"
    "🎯 Где обрабатывать, а где нет: ГЛАВНОЕ — прямо отметь, какие участки/поле НЕ требуют обработки "
    "(чистые), чтобы не обрабатывать сплошь. Если в обследовании есть координаты (GPS) или указания мест — "
    "назови проблемные зоны; если данных по местам нет — так и скажи.\n"
    "💊 План обработок: по каждому мероприятию — объект, препарат (ТОЛЬКО из списка ЗАРЕГИСТРИРОВАННЫХ, с "
    "производителем в [скобках], если указан), норма расхода, машина/способ, оптимальный срок/фаза.\n"
    "♻️ Экономия химии: сравни план с блоком БАЗОВАЯ ОБРАБОТКА (фактические сплошные обработки этого сезона). "
    "Оцени, сколько сплошных обработок можно заменить точечными/зональными и насколько примерно это сократит "
    "расход препаратов и затраты — дай конкретный ориентир в % и, если можешь, в литрах/кг на основе доз и "
    "площади. ОБЯЗАТЕЛЬНО оговори, что точная доля площади определяется только сплошным обследованием "
    "(проход/дрон), а пока это оценка.\n"
    "⏭ Что обследовать дальше: какие наблюдения нужны, чтобы уточнить план в следующий заход.\n\n"
    "ЖЁСТКИЕ ПРАВИЛА: безопасность культуры превыше всего — НЕ рекомендуй препараты, повреждающие саму "
    "культуру (глифосат — сплошной; на подсолнечнике/сое имидазолиноны/трибенурон-метил — ТОЛЬКО на "
    "устойчивых гибридах Clearfield/Express, обязательно оговори это условие). Рекомендуй ТОЛЬКО "
    "зарегистрированные для этой культуры препараты из списка; ничего не выдумывай. Если зарегистрированных "
    "вариантов нет — честно скажи и предложи агроприёмы (севооборот, устойчивый гибрид, механическая "
    "обработка). Без общих дисклеймеров — пиши практично и по делу."
)


def _obs_block(obs) -> str:
    if not obs:
        return ("ОБСЛЕДОВАНИЕ: свежих наблюдений по полю нет — опирайся на историю и севооборот, "
                "и порекомендуй провести обследование поля (проход с фото по всему полю, включая "
                "чистые участки).")
    lines = ["ОБСЛЕДОВАНИЕ (что видели на поле в последних осмотрах):"]
    for o in obs:
        cat = CAT_RU.get(o["category"], o["category"] or "")
        sub = (o["subcategory"] or "").strip()
        note = (o["comment_text"] or o["comment_voice_text"] or "").strip()
        loc = ""
        if o["gps_lat"] is not None and o["gps_lon"] is not None:
            loc = f" [GPS {float(o['gps_lat']):.4f},{float(o['gps_lon']):.4f}]"
        when = o["created_at"].strftime("%d.%m") if o["created_at"] else ""
        lines.append(f"• {when}: {cat}" + (f" — {sub}" if sub else "") + loc
                     + (f" — {note}" if note else ""))
    return "\n".join(lines)


def _prod_block(crop: str, prods) -> str:
    if not prods:
        return (f"ЗАРЕГИСТРИРОВАННЫЕ препараты: в Госкаталоге для культуры «{crop}» подходящих записей "
                f"не найдено — не предлагай конкретные препараты «из головы», опирайся на агроприёмы и "
                f"честно укажи, что нужен подбор зарегистрированных средств.")
    seen, lines = set(), []
    for p in prods:
        if p["product_name"] in seen:
            continue
        seen.add(p["product_name"])
        maker = producer_label(p.get("registrant"))
        tag = f" [{maker}]" if maker else ""
        lines.append(f"• {p['product_name']}{tag} (д.в. {p['active_substances']}) — "
                     f"{p['target']}; норма {p['rate']}")
        if len(lines) >= 25:
            break
    return (f"ЗАРЕГИСТРИРОВАННЫЕ для «{crop}» препараты (Госкаталог) — рекомендуй ТОЛЬКО из этого списка:\n"
            + "\n".join(lines))


def _baseline_block(season, passes, area_ha) -> str:
    """The blanket-spray baseline the plan's savings are measured against (real CropWise)."""
    if not passes:
        return ("БАЗОВАЯ ОБРАБОТКА (факт, CropWise): записей о сплошных обработках СЗР в этом сезоне нет — "
                "сравнивать экономию не с чем, опирайся на типовую практику и оговори это.")
    area = f"{float(area_ha):g} га" if area_ha else "площадь не указана"
    lines = [f"БАЗОВАЯ ОБРАБОТКА (факт по CropWise, сезон {season}; поле {area}) — это сплошные обработки СЗР, "
             f"с которыми сравнивается экономия плана. Всего обработок: {len(passes)}."]
    for p in passes:
        d = p["treatment_date"].strftime("%d.%m") if p["treatment_date"] else ""
        ar = f"{float(p['area_ha']):g} га" if p["area_ha"] is not None else (f"{float(area_ha):g} га" if area_ha else "?")
        lines.append(f"• {d}: {p['product']} — норма {p['dose'] or '?'} на {ar}"
                     + (f", против {p['target']}" if p["target"] else "")
                     + (f", затраты {p['cost']}" if p.get("cost") else ""))
    return "\n".join(lines)


async def generate_field_plan(field_query: str, farm_id: int | None) -> str:
    if not (settings.yc_api_key and settings.yc_folder_id):
        return "План недоступен: не настроен YandexGPT."
    field = await resolve_field(field_query, farm_id)
    if not field:
        return f"Поле не найдено: «{field_query}». Укажите номер поля, например /plan 121/140."
    crop = (field.get("crop") or "").strip()
    card = await field_card_text(field_query, farm_id)
    obs = await get_field_observations(field["id"])
    prods = await get_registered_products(crop) if crop else []
    season, passes = await get_field_protection_baseline(field["id"])

    user_blob = "\n\n".join([
        f"ДАННЫЕ ПО ПОЛЮ:\n{card}",
        _baseline_block(season, passes, field.get("area_ha")),
        _obs_block(obs),
        _prod_block(crop or "—", prods),
        "ЗАДАЧА: составь план работ по этому полю по заданной структуре.",
    ])
    try:
        plan = await asyncio.to_thread(_complete, _PLAN_SYS, user_blob, 1500, 0.3)
    except Exception as exc:
        logger.warning("field plan generation failed: %s", exc)
        return "Не удалось составить план (сервис ИИ недоступен). Попробуйте позже."
    head = f"📋 План работ — {field['name']}" + (f" ({crop})" if crop else "")
    if passes:
        head += f"\nСплошных обработок СЗР в сезоне {season}: {len(passes)} (база для сравнения)"
    return head + "\n\n" + plan
