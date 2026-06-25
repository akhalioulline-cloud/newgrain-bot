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
from bot.epv import epv_block
import re

from bot.db import (
    field_card_text,
    get_farm_products_for_crop,
    get_field_observations,
    get_field_protection_baseline,
    get_product_prices,
    get_registered_products,
    log_plan_run,
    producer_label,
    resolve_field,
)


def parse_dose(s):
    """Free-text dose → (value_per_ha, base_unit in {'л','кг'}) or (None, None).
    Normalises мл→л and г/мг→кг so it matches the price unit. Order matters: check
    кг before г, мл before л."""
    if not s:
        return None, None
    t = str(s).lower().replace(",", ".")
    m = re.search(r"(\d+(?:\.\d+)?)", t)
    if not m:
        return None, None
    val = float(m.group(1))
    if "мл" in t:
        return val / 1000, "л"
    if "кг" in t:
        return val, "кг"
    if "мг" in t:
        return val / 1_000_000, "кг"
    if re.search(r"\bг\b|г/га|г\.", t):
        return val / 1000, "кг"
    if "л" in t:
        return val, "л"
    return None, None


def _baseline_cost(passes, prices, field_area):
    """Deterministic ₽ baseline from the real blanket passes, for products we have a price
    for and a parseable, unit-matching dose. Returns (total_rub, priced_count, total_count)."""
    total, priced = 0.0, 0
    for p in passes:
        val, unit = parse_dose(p["dose"])
        pr = prices.get((p["product"] or "").strip().lower())
        area = float(p["area_ha"]) if p["area_ha"] is not None else (float(field_area) if field_area else None)
        if val and pr and area and pr["unit"] == unit:
            total += val * area * pr["price"]
            priced += 1
    return total, priced, len(passes)

logger = logging.getLogger(__name__)

CAT_RU = {"weed": "сорняк", "disease": "болезнь", "pest": "вредитель",
          "scouting": "обследование", "treatment_result": "после обработки",
          "other": "прочее"}

_PLAN_SYS = (
    "Ты — опытный агроном-консультант хозяйства АО «НЗК» (ЦЧР). На основе ДАННЫХ ПО ПОЛЮ, ОБСЛЕДОВАНИЯ и "
    "списка ЗАРЕГИСТРИРОВАННЫХ препаратов составь ПЛАН ЗАЩИТЫ поля — обычным текстом, без markdown-звёздочек, "
    "по разделам с такими заголовками-значками:\n"
    "🗺 Состояние поля: культура и её фаза, что показывают обследование и история — 1–2 фразы.\n"
    "🌱 Спектр сорняков и фаза: перечисли наблюдаемые сорняки ПО СЕМЕЙСТВАМ (двудольные / злаковые; "
    "однолетние / многолетние корнеотпрысковые, напр. осот) и их фазу роста. Помни: разные семейства всходят "
    "ВОЛНАМИ в разные сроки, семенной банк по всему полю.\n"
    "⏱ Срок (ЭПВ): нужно обрабатывать сейчас или ещё мониторить? Большинство гербицидов КОНТАКТНЫЕ, без "
    "почвенного (остаточного) действия — поэтому ждут максимально допустимой фазы сорняка и достижения ЭПВ "
    "(экономический порог вредоносности), и тогда работают СПЛОШЬ по полю. ЕСЛИ дан блок ЭПВ ХОЗЯЙСТВА — "
    "сравнивай наблюдаемую засорённость именно с ЭТИМИ порогами хозяйства (по каждой группе сорняков), "
    "назови порог и фазу учёта явно, и по ним реши: достигнут ли ЭПВ и в какой фазе обрабатывать. Оцени: "
    "хватит ли ОДНОЙ обработки или по новой волне понадобится вторая (используй ориентир по числу обработок "
    "из блока ЭПВ ХОЗЯЙСТВА).\n"
    "💊 Препараты и норма: подходящие под наблюдаемый спектр и фазу препараты — ТОЛЬКО из списка "
    "ЗАРЕГИСТРИРОВАННЫХ (с производителем в [скобках], если указан), с нормой расхода. ЕСЛИ есть блок "
    "ПРЕПАРАТЫ ХОЗЯЙСТВА — при прочих равных ПРЕДПОЧИТАЙ препараты из него (хозяйство ими реально работает и "
    "они в наличии), при условии что они подходят под спектр и зарегистрированы. НЕ завышай норму ради "
    "переросших сорняков — это даёт последействие и угнетает культуру.\n"
    "⚠️ Безопасность культуры: предупреди про последействие/фитотоксичность и условия применения.\n"
    "♻️ Как сэкономить: сравни с блоком БАЗОВАЯ ОБРАБОТКА. Экономия НЕ в обработке части площади — поле "
    "обрабатывают сплошь (сорняки всходят по всему полю). Экономия в ПРАВИЛЬНОМ РЕШЕНИИ: верный СРОК (одна "
    "обработка вместо двух, где это реально), верный ПРЕПАРАТ под спектр (не промахнуться мимо семейства → не "
    "делать лишний проход), верная НОРМА (без перерасхода и без угнетения культуры). Дай ориентир по числу "
    "обработок и, если есть цены, по экономии в рублях относительно базы.\n"
    "⏭ Что мониторить дальше: какие наблюдения нужны, чтобы поймать ЭПВ и новую волну сорняков.\n\n"
    "ЖЁСТКИЕ ПРАВИЛА:\n"
    "• НЕ предлагай точечную/зональную обработку ЧАСТИ поля для гербицидов на яровых культурах — поле "
    "обрабатывают сплошь; «обработать только N% площади» — НЕВЕРНО.\n"
    "• Срок привязывай к фазе сорняка и ЭПВ (контактные препараты не имеют почвенного действия — рано "
    "обрабатывать бессмысленно, новая волна выживет).\n"
    "• Безопасность культуры превыше всего; НЕ завышай нормы (последействие). Рекомендуй ТОЛЬКО "
    "зарегистрированные для этой культуры препараты из списка, ничего не выдумывай. На сое/подсолнечнике "
    "имидазолиноны/трибенурон-метил — ТОЛЬКО на устойчивых гибридах Clearfield/Express (оговори это).\n"
    "• Если зарегистрированных вариантов мало — честно скажи и предложи агроприёмы (севооборот, устойчивый "
    "гибрид, сроки сева). Без общих дисклеймеров — практично и по делу."
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


def _farm_products_block(rows) -> str:
    if not rows:
        return ""
    lines = ["ПРЕПАРАТЫ ХОЗЯЙСТВА на этой культуре (реальная практика по CropWise — при прочих равных "
             "предпочитай их; в списке возможны прилипатели/адъюванты — это добавки, не гербициды):"]
    for r in rows:
        a_s = (r["active_substance"] or "").strip()
        lines.append(f"• {r['product']} — применяли {r['passes']} раз, обычно {r['typ_dose'] or '?'}"
                     + (f" (д.в. {a_s})" if a_s else ""))
    return "\n".join(lines)


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


async def generate_field_plan(field_query: str, farm_id: int | None, ran_by=None) -> str:
    if not (settings.yc_api_key and settings.yc_folder_id):
        return "План недоступен: не настроен YandexGPT."
    field = await resolve_field(field_query, farm_id)
    if not field:
        return f"Поле не найдено: «{field_query}». Укажите номер поля, например /plan 121/140."
    crop = (field.get("crop") or "").strip()
    card = await field_card_text(field_query, farm_id)
    obs = await get_field_observations(field["id"])
    prods = await get_registered_products(crop) if crop else []
    farm_prods = await get_farm_products_for_crop(farm_id, crop) if crop else []
    season, passes = await get_field_protection_baseline(field["id"])
    prices = await get_product_prices()
    cost_rub, priced, n_pass = _baseline_cost(passes, prices, field.get("area_ha"))
    cost_line = ""
    if priced:
        cost_line = (f"ФАКТИЧЕСКИЕ ЗАТРАТЫ НА СЗР (сезон {season}, по {priced} из {n_pass} обработок с известной "
                     f"ценой): ≈ {cost_rub:,.0f} ₽ за сезон. Это база в рублях для сравнения — экономия идёт от "
                     f"меньшего ЧИСЛА обработок (верный срок), верного препарата и нормы, а НЕ от обработки части "
                     f"площади.".replace(",", " "))

    user_blob = "\n\n".join(p for p in [
        f"ДАННЫЕ ПО ПОЛЮ:\n{card}",
        _baseline_block(season, passes, field.get("area_ha")),
        cost_line or None,
        _obs_block(obs),
        epv_block(crop) or None,
        _farm_products_block(farm_prods) or None,
        _prod_block(crop or "—", prods),
        "ЗАДАЧА: составь план работ по этому полю по заданной структуре.",
    ] if p)
    try:
        plan = await asyncio.to_thread(_complete, _PLAN_SYS, user_blob, 1500, 0.3)
    except Exception as exc:
        logger.warning("field plan generation failed: %s", exc)
        return "Не удалось составить план (сервис ИИ недоступен). Попробуйте позже."
    head = f"📋 План работ — {field['name']}" + (f" ({crop})" if crop else "")
    if passes:
        head += f"\nСплошных обработок СЗР в сезоне {season}: {len(passes)}"
        if priced:
            head += f" · затраты ≈ {cost_rub:,.0f} ₽".replace(",", " ")
        head += " (база для сравнения)"
    full = head + "\n\n" + plan
    await log_plan_run(field["id"], field["name"], season, len(passes) if passes else 0,
                       round(cost_rub, 2) if priced else None, full, ran_by)
    return full
