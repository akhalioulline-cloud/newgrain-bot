"""Colloquial Q&A for agronomists. Answers a free-text question grounded in the
field's CropWise data (passed in as context) + general agronomy knowledge, via
YandexGPT (in-RU, same key as parse_op/translate). Returns None on failure so the
caller can fall back gracefully.
"""
import asyncio
import json
import re

import requests

from bot.config import settings
from bot.db import get_registered_products, producer_label, search_literature

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
    "Ты — опытный агроном-консультант хозяйства «New Grain Co» (Центрально-Чернозёмный "
    "регион). Отвечай как живой коллега в поле: коротко, дружелюбно, по делу, активным "
    "залогом, без канцелярита и общих фраз. "
    "Если ниже есть блок «ДАННЫЕ ПО ПОЛЮ» (реальные операции и показатели из CropWise) — "
    "опирайся на него и не придумывай операции, которых там нет; называй даты, препараты "
    "и нормы как в данных. "
    "Если спрашивают, как пользоваться ботом или как фотографировать — отвечай простыми "
    "словами по справке ниже. "
    "На агрономические вопросы давай КОНКРЕТНЫЙ ответ: называй торговые названия препаратов "
    "и действующее вещество, типичные нормы расхода (л/га или кг/га), фазу применения и "
    "против чего. Сначала точно пойми, о чём речь (например «осот» — это сорняк, нужен "
    "гербицид, а не инсектицид). Если в контексте есть блок «ЗАРЕГИСТРИРОВАННЫЕ ПРЕПАРАТЫ» "
    "(это реальный Госкаталог) — рекомендуй препараты и нормы ТОЛЬКО из этого списка, "
    "выбирая 2–3 подходящих под задачу; не называй препаратов вне списка. "
    "⚠️ БЕЗОПАСНОСТЬ КУЛЬТУРЫ — главное правило: никогда не рекомендуй препарат, который "
    "повредит саму культуру. Сплошные гербициды (глифосат) убивают культуру — нельзя по "
    "вегетирующим посевам. На ШИРОКОЛИСТНОЙ культуре (подсолнечник, соя) обычные "
    "противодвудольные и гормональные гербициды (2,4-Д, дикамба, клопиралид, трибенурон и "
    "т.п.) применимы ТОЛЬКО на устойчивых гибридах (Clearfield/имидазолиноны, Express/"
    "трибенурон-устойчивые) — обязательно оговаривай это условие. Если подходящего "
    "селективного препарата для этой культуры нет — честно скажи об этом и предложи "
    "агроприёмы (нужный гибрид, севооборот, механическую прополку), а НЕ опасный препарат. "
    "Если у препарата в списке есть метка производителя в [скобках] (Syngenta, Bayer, BASF, "
    "Corteva, FMC, Adama, Август, Щёлково Агрохим) — указывай производителя рядом с препаратом "
    "в ответе, например «Корсар (Август)». Препараты без метки — другие производители, их тоже "
    "можно рекомендовать. "
    "Если есть блок «НАУЧНЫЕ ИСТОЧНИКИ» — при ответе по теме можешь кратко сослаться на "
    "1–2 из них (название + ссылка), но только если они реально относятся к вопросу; не "
    "выдумывай источники и не приписывай им выводов сверх аннотации. "
    "Не пиши дисклеймеры («разрешённых к применению в РФ», "
    "«зарегистрированных в Госкаталоге») и не отсылай «ознакомьтесь с каталогом» — сразу "
    "давай дельный совет. Если по конкретному препарату или норме не уверен — коротко "
    "скажи об этом, не выдумывай. "
    "Если вопрос НЕ про поля/обработки хозяйства, не про агрономию и не про работу с "
    "ботом — или непонятен — вежливо скажи, что ты помощник агронома, и подскажи, с чем "
    "можешь помочь.\n\n"
    + _BOT_GUIDE
)


def _complete(system_text: str, user_text: str, max_tokens: int, temperature: float) -> str:
    body = {
        "modelUri": f"gpt://{settings.yc_folder_id}/{settings.yc_translate_model}",
        "completionOptions": {"stream": False, "temperature": temperature, "maxTokens": max_tokens},
        "messages": [{"role": "system", "text": system_text}, {"role": "user", "text": user_text}],
    }
    r = requests.post(_ENDPOINT, headers={"Authorization": f"Api-Key {settings.yc_api_key}"},
                      json=body, timeout=45)
    r.raise_for_status()
    return r.json()["result"]["alternatives"][0]["message"]["text"].strip()


_REC_RE = re.compile(
    r"обработ|опрыск|препарат|гербицид|фунгицид|инсектицид|протрав|против|"
    r"боро|борьб|уничтож|избав|подави|вывест|потрав|сорняк|вредител|болезн|защит|"
    r"чем\s+.*\s(от|с)\s", re.I)

_EXTRACT_SYS = (
    "Из вопроса агронома про защиту растений извлеки:\n"
    "crop — КУЛЬТУРА (соя, подсолнечник, пшеница, кукуруза, ячмень, рапс и т.п.), иначе null\n"
    "target — короткий корень названия вредного объекта для поиска (осот, амбрози, живокост, "
    "марь, щириц, тля, ржавчин, фузариоз и т.п.), иначе null\n"
    "weed_class — если объект СОРНЯК, его класс: «двудольн» (широколистный: осот, амброзия, "
    "живокость, марь, щирица, вьюнок) или «злаков» (злаковые/мятликовые травы); если объект "
    "не сорняк (вредитель/болезнь) или класс неясен — null\n"
    'Верни ТОЛЬКО JSON: {"crop":...,"target":...,"weed_class":...}. '
    "Если вопрос не про подбор препарата/обработку — все null."
)


def _clean_json(s):
    s = re.sub(r"^```(?:json)?|```$", "", (s or "").strip(), flags=re.M).strip()
    m = re.search(r"\{.*\}", s, re.S)
    return json.loads(m.group(0)) if m else None


async def _registry_grounding(question: str) -> str | None:
    """For a «чем обработать культуру X от Y» question, pull registered products from the
    Госкаталог so the answer stays correct (real, registered options only)."""
    if not _REC_RE.search(question):
        return None
    try:
        ct = _clean_json(await asyncio.to_thread(_complete, _EXTRACT_SYS, question, 200, 0.0))
    except Exception:
        return None
    if not ct or not ct.get("crop"):
        return None
    crop, target, klass = ct["crop"], ct.get("target"), ct.get("weed_class")
    prods = await get_registered_products(crop, target) if target else []
    used = target
    if not prods and klass:                  # «живокость»(0) → «двудольн»(30): the real options
        prods = await get_registered_products(crop, klass)
        used = klass
    if not prods and not target and not klass:   # generic «чем обработать подсолнечник»
        prods = await get_registered_products(crop)
    if not prods:
        # crop is known but nothing is registered for this object → forbid crop-killers
        return (f"В Госкаталоге НЕТ зарегистрированного для «{crop}» препарата против "
                f"«{target or 'этого объекта'}». НЕ рекомендуй неселективные препараты "
                f"(глифосат и т.п.) и средства для других культур — они повредят «{crop}». "
                "Честно скажи, что зарегистрированных селективных вариантов нет или мало, и "
                "предложи агроприёмы (подходящий гибрид Clearfield/Express, севооборот, "
                "механическую прополку).")
    seen, lines = set(), []
    for p in prods:
        if p["product_name"] in seen:
            continue
        seen.add(p["product_name"])
        maker = producer_label(p.get("registrant"))   # tag major producers inline
        tag = f" [{maker}]" if maker else ""
        lines.append(f"• {p['product_name']}{tag} (д.в. {p['active_substances']}) — "
                     f"{p['target']}; норма {p['rate']}")
        if len(lines) >= 20:
            break
    head = (f"ЗАРЕГИСТРИРОВАННЫЕ для «{crop}» препараты (Госкаталог)"
            + (f" против «{used}»" if used else "")
            + " — рекомендуй ТОЛЬКО из этого списка (зарегистрированы для этой культуры). "
            "Метка в [скобках] — производитель: укажи его рядом с препаратом в ответе:")
    head += ("\n(Проверка на здравый смысл: если по действующему веществу препарат явно "
             "предназначен для ДРУГОЙ культуры — напр. десмедифам/фенмедифам (Бетанал) только "
             "для свёклы — НЕ рекомендуй его, даже если он оказался в списке.)")
    if re.search(r"подсолн|со[яи]|рапс", crop, re.I):
        head += ("\n(ОБЯЗАТЕЛЬНО предупреди: на подсолнечнике/сое препараты на трибенурон-"
                 "метиле (система Express/Sumo) и на имазамоксе/имазапире (Clearfield) "
                 "применимы ТОЛЬКО на устойчивых к ним гибридах — на обычных они повредят "
                 "культуру. Укажи это условие в ответе.)")
    return head + "\n" + "\n".join(lines)


async def _literature_grounding(question: str) -> str | None:
    """Relevant open-access (CC BY) agronomy articles for the question — the bot may cite
    them (author, year, link). Attribution is exactly what the CC BY licence requires."""
    try:
        arts = await search_literature(question, limit=3)
    except Exception:
        return None
    if not arts:
        return None
    out = ["НАУЧНЫЕ ИСТОЧНИКИ (CyberLeninka, открытый доступ, CC BY) — если по теме, сошлись "
           "на 1–2 (название, авторы, год, ссылка); не приписывай им выводов сверх аннотации:"]
    for a in arts:
        cite = (f"«{a['title']}»" + (f" — {a['authors']}" if a["authors"] else "")
                + (f", {a['year']}" if a["year"] else "") + f" — {a['url']}")
        out.append("• " + cite + (f"\n  {a['abstract'][:280]}" if a["abstract"] else ""))
    return "\n".join(out)


# Structured format for product-recommendation questions («чем обработать сою от осота?») —
# same clarity as the photo diagnosis, minus the vision sections (the object is already named).
# Used only when registry grounding fired (a real crop+target protection question); how-to and
# field-history questions keep the conversational _SYS.
_REC_SYS = (
    "Ты — опытный агроном-консультант хозяйства «New Grain Co» (ЦЧР). Ответь на вопрос о защите "
    "растений СТРУКТУРИРОВАННО, обычным текстом (БЕЗ markdown-звёздочек), по разделам с такими "
    "заголовками-значками:\n"
    "🌿 Объект: одной фразой что это (тип сорняка/болезни/вредителя, особенности — напр. осот "
    "многолетний корнеотпрысковый).\n"
    "🛡 Меры борьбы: 1) агротехнически/механически; 2) химически.\n"
    "💊 Препараты: 2–3 подходящих с нормой расхода. Если в контексте есть блок ЗАРЕГИСТРИРОВАННЫЕ "
    "ПРЕПАРАТЫ — бери препараты ТОЛЬКО из него, с пометкой производителя в [скобках], если она "
    "есть. Если блока нет — назови действующие вещества и попроси уточнить культуру.\n"
    "⏱ Когда обрабатывать: оптимальная фаза культуры и сорняка.\n"
    "📚 Источники: если в контексте есть блок НАУЧНЫЕ ИСТОЧНИКИ — добавь 1–2 ссылки.\n\n"
    "ЖЁСТКИЕ ПРАВИЛА: безопасность культуры превыше всего — НЕ рекомендуй препараты, повреждающие "
    "саму культуру (глифосат — сплошной; на подсолнечнике/сое противодвудольные, трибенурон-метил, "
    "имидазолиноны — ТОЛЬКО на устойчивых гибридах Express/Clearfield, обязательно оговори это). "
    "Не выдумывай препаратов вне списка; если зарегистрированных нет — честно скажи и предложи "
    "агроприёмы. Без дисклеймеров («разрешённых в РФ», «ознакомьтесь с каталогом») — сразу по делу."
)


async def answer(question: str, context: str | None = None,
                 history: str | None = None) -> str | None:
    if not (settings.yc_api_key and settings.yc_folder_id):
        return None
    # Follow-ups («предложите варианты», «а норма?») carry the crop/target in the PREVIOUS turn —
    # fold the last user question from history into the grounding query so products still resolve.
    ground_q = question
    if history:
        prev_qs = re.findall(r"Пользователь:\s*(.+)", history)
        if prev_qs:
            ground_q = f"{prev_qs[-1].strip()}. {question}"
    grounding = await _registry_grounding(ground_q)
    literature = await _literature_grounding(ground_q)
    parts = [p for p in (
        f"ДАННЫЕ ПО ПОЛЮ:\n{context}" if context else None,
        (f"ПРЕДЫДУЩИЙ ДИАЛОГ (контекст для уточняющих вопросов и расчётов; "
         f"опирайся на него, если вопрос ссылается на «предыдущий ответ»):\n{history}"
         if history else None),
        grounding,
        literature,
        f"ВОПРОС: {question}",
    ) if p]
    # Structured answer for real recommendation questions (grounding fired); conversational
    # otherwise (bot how-to, field history, off-topic).
    sys, max_toks = (_REC_SYS, 950) if grounding else (_SYS, 700)
    try:
        return await asyncio.to_thread(_complete, sys, "\n\n".join(parts), max_toks, 0.45)
    except Exception:
        return None
