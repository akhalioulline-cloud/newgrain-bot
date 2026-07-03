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
from bot.epv import epv_block
from bot import wiki_source

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
    "регион). Отвечай как живой коллега в поле: конкретно, по делу и с достаточной детализацией "
    "(2–4 практических пункта, не обрывай на одном), дружелюбно, активным "
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
    "ТОЛЬКО РЕШЕНИЯ И ДЕЙСТВИЯ. НЕ пиши: дисклеймеры («разрешённых в РФ», «ознакомьтесь с "
    "каталогом»); отговорки «обратитесь к специалистам», «в предоставленном контексте нет…»; "
    "нравоучения и предупреждения на будущее («чтобы избежать в будущем», «важно строго "
    "соблюдать рекомендации/дозировки»). Если данных мало — дай ЛУЧШИЙ практический вариант по "
    "сути, а не отговорку. При повреждении/стрессе самой культуры (например, гербицидный ожог) "
    "сразу называй конкретные меры восстановления: антистресс/стимулятор роста с нормой, "
    "подкормка (какая), агроприёмы. Если по конкретному препарату или норме не уверен — коротко "
    "скажи об этом, не выдумывай. "
    "Если вопрос НЕ про поля/обработки хозяйства, не про агрономию и не про работу с "
    "ботом — или непонятен — вежливо скажи, что ты помощник агронома, и подскажи, с чем "
    "можешь помочь.\n\n"
    + _BOT_GUIDE
)


def _complete(system_text: str, user_text: str, max_tokens: int, temperature: float,
              model: str | None = None) -> str:
    body = {
        "modelUri": f"gpt://{settings.yc_folder_id}/{model or settings.yc_chat_model}",
        "completionOptions": {"stream": False, "temperature": temperature, "maxTokens": max_tokens},
        "messages": [{"role": "system", "text": system_text}, {"role": "user", "text": user_text}],
    }
    r = requests.post(_ENDPOINT, headers={"Authorization": f"Api-Key {settings.yc_api_key}"},
                      json=body, timeout=45)
    r.raise_for_status()
    return r.json()["result"]["alternatives"][0]["message"]["text"].strip()


def _complete_stream(system_text: str, user_text: str, max_tokens: int, temperature: float,
                     model: str | None = None):
    """Stream a completion as text DELTAS. YandexGPT sends the full text-so-far in each
    chunk (cumulative), so we diff against what we've already emitted. Sync generator —
    Starlette iterates it in a threadpool, so it won't block the event loop."""
    body = {
        "modelUri": f"gpt://{settings.yc_folder_id}/{model or settings.yc_chat_model}",
        "completionOptions": {"stream": True, "temperature": temperature, "maxTokens": max_tokens},
        "messages": [{"role": "system", "text": system_text}, {"role": "user", "text": user_text}],
    }
    with requests.post(_ENDPOINT, headers={"Authorization": f"Api-Key {settings.yc_api_key}"},
                       json=body, timeout=60, stream=True) as r:
        r.raise_for_status()
        prev = ""
        for line in r.iter_lines():
            if not line:
                continue
            try:
                txt = json.loads(line)["result"]["alternatives"][0]["message"]["text"]
            except (ValueError, KeyError, IndexError):
                continue
            delta = txt[len(prev):] if txt.startswith(prev) else txt   # rare re-base → emit fresh
            if delta:
                yield delta
            prev = txt


_REC_RE = re.compile(
    r"обработ|опрыск|препарат|гербицид|фунгицид|инсектицид|протрав|против|"
    r"боро|борьб|уничтож|избав|подави|вывест|потрав|сорняк|падалиц|самосев|вредител|болезн|защит|"
    r"чем\s+.*\s(от|с)\s", re.I)

_EXTRACT_SYS = (
    "Из вопроса агронома про защиту растений извлеки:\n"
    "crop — КУЛЬТУРА (соя, подсолнечник, пшеница, кукуруза, ячмень, рапс и т.п.), иначе null\n"
    "target — короткий корень названия вредного объекта для поиска (осот, амбрози, живокост, "
    "марь, щириц, тля, ржавчин, фузариоз и т.п.), иначе null\n"
    "weed_class — если объект СОРНЯК, его класс: «двудольн» (широколистный: осот, амброзия, "
    "живокость, марь, щирица, вьюнок) или «злаков» (злаковые/мятликовые травы); если объект "
    "не сорняк (вредитель/болезнь) или класс неясен — null\n"
    "ПАДАЛИЦА/САМОСЕВ (всходы из осыпавшихся семян прошлой культуры) — это СОРНЯК: падалица "
    "подсолнечника, рапса, сои, гороха, льна → weed_class «двудольн»; падалица пшеницы, ячменя, "
    "ржи, кукурузы, овса и других злаков → «злаков». target для падалицы — «падалиц».\n"
    'Верни ТОЛЬКО JSON: {"crop":...,"target":...,"weed_class":...}. '
    "Если вопрос не про подбор препарата/обработку — все null."
)


def _clean_json(s):
    s = re.sub(r"^```(?:json)?|```$", "", (s or "").strip(), flags=re.M).strip()
    m = re.search(r"\{.*\}", s, re.S)
    return json.loads(m.group(0)) if m else None


# Deterministic crop+target resolution for the common protection questions, so we DON'T
# spend a second LLM round-trip on extraction. Misses fall through to the lite-model
# extractor. Padalitsa/самосев is deliberately left to the LLM (the weed class depends
# on which crop's volunteers, not the field crop).
_CROP_LEX = [
    ("подсолн", "подсолнечник"), ("кукуруз", "кукуруза"), ("пшениц", "пшеница"),
    ("ячмен", "ячмень"), ("рапс", "рапс"), ("горох", "горох"),
    ("свёкл", "сахарная свёкла"), ("свекл", "сахарная свёкла"),
    ("соя", "соя"), ("сои", "соя"), ("сою", "соя"), ("сое", "соя"),
]
_WEED_LEX = [
    # двудольные (broadleaf)
    ("осот", ("осот", "двудольн")), ("бодяк", ("бодяк", "двудольн")),
    ("амбрози", ("амбрози", "двудольн")), ("щириц", ("щириц", "двудольн")),
    ("марь", ("марь", "двудольн")), ("лебед", ("марь", "двудольн")),
    ("вьюнок", ("вьюнок", "двудольн")), ("вьюнк", ("вьюнок", "двудольн")),
    ("горец", ("горец", "двудольн")), ("гречишк", ("гречишк", "двудольн")),
    ("ромашк", ("ромашк", "двудольн")), ("подмаренник", ("подмаренник", "двудольн")),
    ("дурнишник", ("дурнишник", "двудольн")), ("канатник", ("канатник", "двудольн")),
    ("василёк", ("василёк", "двудольн")), ("василек", ("василёк", "двудольн")),
    ("молочай", ("молочай", "двудольн")), ("паслён", ("паслён", "двудольн")),
    ("паслен", ("паслён", "двудольн")), ("звездчатк", ("звездчатк", "двудольн")),
    ("пастушь", ("пастушья сумка", "двудольн")), ("ярутк", ("ярутка", "двудольн")),
    # злаковые (grass)
    ("щетинник", ("щетинник", "злаков")), ("мышей", ("щетинник", "злаков")),
    ("ежовник", ("ежовник", "злаков")), ("куриное просо", ("ежовник", "злаков")),
    ("пырей", ("пырей", "злаков")), ("овсюг", ("овсюг", "злаков")),
    ("метлиц", ("метлица", "злаков")), ("костёр", ("костёр", "злаков")),
    ("костер", ("костёр", "злаков")), ("лисохвост", ("лисохвост", "злаков")),
    ("росичк", ("росичк", "злаков")), ("мятлик", ("мятлик", "злаков")),
]


def _lexicon_extract(question: str):
    """Resolve {crop, target, weed_class} from a compact lexicon — no LLM call. Returns
    None (→ fall back to the lite-model extractor) when the crop or the weed isn't
    confidently in the lexicon, or for padalitsa (weed class is nuanced there)."""
    ql = f" {question.lower()} "
    if "падалиц" in ql or "самосев" in ql:
        return None
    crop = next((c for stem, c in _CROP_LEX if stem in ql), None)
    if not crop:
        return None
    for stem, (target, klass) in _WEED_LEX:
        if stem in ql:
            return {"crop": crop, "target": target, "weed_class": klass}
    return None


async def _extract_ct(question: str):
    """Resolve {crop, target, weed_class} for a protection question — lexicon fast-path
    (no LLM), else the pro extractor on a miss. None if not a protection question or
    nothing resolved. Extracted once and shared by product + Wikipedia grounding."""
    if not _REC_RE.search(question):
        return None
    ct = _lexicon_extract(question)          # no-LLM fast path — kills the second call on common questions
    if ct is None:                           # miss → the capable extractor
        try:
            ct = _clean_json(await asyncio.to_thread(
                _complete, _EXTRACT_SYS, question, 200, 0.0, settings.yc_extract_model))
        except Exception:
            return None
    return ct if (ct and ct.get("crop")) else None


async def _registry_grounding(question: str, ct) -> str | None:
    """For a «чем обработать культуру X от Y» question, pull registered products from the
    Госкаталог so the answer stays correct (real, registered options only)."""
    if not ct:
        return None
    crop, target, klass = ct["crop"], ct.get("target"), ct.get("weed_class")
    prods = await get_registered_products(crop, target) if target else []
    used = target
    # A narrow target («осот» → 3 products, mostly one maker) hides the real choice: the whole weed
    # CLASS is registered and works (осот is двудольный). Widen to the class so the answer shows the
    # true brand spread (Август/Bayer/Щёлково/BASF…) — target-specific first, then the rest, deduped.
    if klass and len(prods) < 6:
        extra = await get_registered_products(crop, klass)
        seen = {p["product_name"] for p in prods}
        prods = list(prods) + [p for p in extra if p["product_name"] not in seen]
        used = target or klass
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
        # No target text here on purpose — it's the generic «однолетние двудольные…» phrase the
        # model would echo on every line. Feed only what differentiates: name, maker, д.в., dose.
        lines.append(f"• {p['product_name']}{tag} — д.в. {p['active_substances']}, норма {p['rate']}")
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
    "💊 Препараты: 4–5 подходящих, по возможности РАЗНЫХ производителей. Каждый — ОДНОЙ КОРОТКОЙ строкой: "
    "«Название [Производитель] — д.в., норма; отличие». В «отличие» дай РЕАЛЬНЫЙ признак, разный у "
    "препаратов: контактный или системный; по листу (послевсходовый) или почвенный (довсходовый); "
    "скорость; особый спектр или ограничение. НИКОГДА не пиши общие для всех фразы «эффективен/действует "
    "против двудольных сорняков» и «норма зависит от культуры» — ЗАПРЕЩЕНЫ. Если реального отличия нет — "
    "оставь только название, д.в. и норму. "
    "Пометку [Производитель] ставь только если он известен, иначе скобки не пиши (не пиши «[не указан]»). "
    "Из блока ЗАРЕГИСТРИРОВАННЫЕ ПРЕПАРАТЫ бери ТОЛЬКО оттуда. НЕ ранжируй эффективность. Если блока нет — "
    "назови д.в. и попроси уточнить культуру.\n"
    "Если блока «ЗАРЕГИСТРИРОВАННЫЕ ПРЕПАРАТЫ» нет (культура не указана) — НЕ выдумывай торговые названия "
    "и производителей; назови 2–3 подходящих действующих вещества и попроси указать культуру для точных "
    "препаратов и норм.\n"
    "⏱ Когда обрабатывать: оптимальная фаза культуры и сорняка.\n"
    "📚 Источники: если в контексте есть блок НАУЧНЫЕ ИСТОЧНИКИ — добавь 1–2 ссылки.\n\n"
    "ЖЁСТКИЕ ПРАВИЛА: безопасность культуры превыше всего — НЕ рекомендуй препараты, повреждающие "
    "саму культуру (глифосат — сплошной; на подсолнечнике/сое противодвудольные, трибенурон-метил, "
    "имидазолиноны — ТОЛЬКО на устойчивых гибридах Express/Clearfield, обязательно оговори это). "
    "Не выдумывай препаратов вне списка; если зарегистрированных нет — честно скажи и предложи "
    "агроприёмы. ТОЛЬКО решения и действия — без дисклеймеров, без «обратитесь к специалистам» и "
    "без нравоучений на будущее («важно соблюдать рекомендации» и т.п.); сразу по делу."
)


# Structured answer for the «Что это?» scan journey — one consistent icon layout for ANY object
# (weed / disease / pest / crop damage), so the card never flips between formats. Keeps the same
# grounding (Госкаталог + ЭПВ + literature) when present.
_SCAN_SYS = (
    "Ты — опытный агроном-консультант хозяйства «New Grain Co» (ЦЧР). По фото распознан объект "
    "(сорняк / болезнь / вредитель / повреждение или состояние самой культуры). Ответь СТРУКТУРИРОВАННО, "
    "обычным текстом БЕЗ markdown-звёздочек, строго тремя разделами с этими значками-заголовками:\n"
    "🔎 Что это: 1–2 фразы — что за объект/состояние и ключевая особенность.\n"
    "💊 Что делать: конкретные меры по пунктам:\n"
    "   • СОРНЯК — препараты ТОЛЬКО из блока «ЗАРЕГИСТРИРОВАННЫЕ ПРЕПАРАТЫ» (если он есть): 4–5 подходящих, "
    "по возможности РАЗНЫХ производителей. Каждый — ОДНОЙ КОРОТКОЙ строкой в формате: «Название "
    "[Производитель] — д.в., норма; отличие». В «отличие» дай РЕАЛЬНЫЙ признак, разный у препаратов: "
    "контактный или системный; по листу (послевсходовый) или почвенный (довсходовый); скорость; особый "
    "спектр или ограничение (напр. только на устойчивых гибридах). НИКОГДА не пиши общие для всех фразы "
    "«эффективен/действует против двудольных сорняков» и «норма зависит от культуры» — они ЗАПРЕЩЕНЫ. "
    "Если реального отличия нет — оставь только название, д.в. и норму, "
    "без общей фразы. Пометку [Производитель] ставь ТОЛЬКО если он известен (Syngenta/Август/BASF/Bayer/"
    "Corteva/Щёлково и т.п.); иначе скобки НЕ пиши (не пиши «[не указан]»). НЕ ранжируй эффективность "
    "брендов. Плюс 1 агроприём. Если блока «ЗАРЕГИСТРИРОВАННЫЕ ПРЕПАРАТЫ» НЕТ (культура не указана) — "
    "НЕ выдумывай торговые названия, производителей [в скобках] и НЕ пиши «норма согласно инструкции»; "
    "назови 2–3 подходящих ДЕЙСТВУЮЩИХ ВЕЩЕСТВА (для пырея/злаковых — граминициды: клетодим, хизалофоп-"
    "этил и т.п.) и попроси указать культуру — тогда дашь точные препараты с нормами.\n"
    "   • БОЛЕЗНЬ или ВРЕДИТЕЛЬ — чем защитить/лечить: препарат(ы) с нормой + агроприём.\n"
    "   • ПОВРЕЖДЕНИЕ/СТРЕСС САМОЙ КУЛЬТУРЫ (гербицидный ожог, дефицит питания и т.п.) — меры "
    "восстановления: антистресс/стимулятор роста с нормой (напр. Эпин, Циркон), подкормка (какими "
    "элементами), агроприёмы (полив, рыхление). НЕ предлагай гербициды/пестициды против самой культуры.\n"
    "⏱ Когда/сроки: сорняк — оптимальная фаза и по ЭПВ (бери блок ЭПВ, если есть), сколько обработок; "
    "болезнь/вредитель — фаза; восстановление — когда ждать эффект и нужен ли повтор.\n\n"
    "ЖЁСТКИЕ ПРАВИЛА: безопасность культуры превыше всего — НЕ рекомендуй препараты, повреждающие саму "
    "культуру (глифосат — сплошной; на подсолнечнике/сое противодвудольные, трибенурон-метил, "
    "имидазолиноны — ТОЛЬКО на устойчивых гибридах Express/Clearfield, оговори это). ТОЛЬКО решения — без "
    "дисклеймеров, без «обратитесь к специалистам», без нравоучений на будущее. Не выдумывай препаратов "
    "вне списка. Если есть блок НАУЧНЫЕ ИСТОЧНИКИ — можешь добавить 1 ссылку в конце."
)


_EPV_RE = re.compile(
    r"эпв|порог|обраб|опрыск|защит|гербицид|фунгицид|инсектицид|сорняк|вредител|болезн|"
    r"пора\b|когда\b|стади|фаз[аеуы]|сколько.*обработ|одну?.*или.*дв|нужно ли|стоит ли", re.I)


def _epv_grounding(question: str) -> str | None:
    """Inject the farm's OWN ЭПВ thresholds (chief agronomist A.K. Kasumov's sheet, bot/epv.py)
    when the question is about treatment timing / thresholds / pass-count and a pilot crop is
    named. The chat's authoritative anchor for «пора ли обрабатывать / сколько обработок» —
    same source /plan already uses. Fully owned data, no external-licence question."""
    if not _EPV_RE.search(question):
        return None
    return epv_block(question) or None      # epv._match substring-detects the crop in the text


# Biology/identification intent — the questions where a Wikipedia species description helps
# (as opposed to «what to spray», which the Госкаталог/ЭПВ already cover).
_BIO_RE = re.compile(
    r"что за|что это|как выглядит|как отлич|отличить|биолог|признак|чем опас|вред(?:ит|онос)|"
    r"жизненн|описан|распозна|определ|как понять|что такое", re.I)


def _weed_term(question: str) -> str | None:
    """A weed object mentioned in the question (from the lexicon), even without a crop —
    so a pure «что за растение амброзия» still finds a species to look up on Wikipedia."""
    ql = f" {question.lower()} "
    for stem, (target, _klass) in _WEED_LEX:
        if stem in ql:
            return target
    return None


async def _wikipedia_grounding(question: str, ct) -> str | None:
    """RU Wikipedia intro on the species/object — biology, morphology, phenology. Fires on
    identification/biology intent when we can name the object (from the shared extraction or
    the weed lexicon). CC BY-SA (founder-approved, LICENSING §6 v1.2): model paraphrases and
    cites the link. Best-effort, runs concurrently with the other grounding."""
    if not _BIO_RE.search(question):
        return None
    term = (ct.get("target") if ct else None) or _weed_term(question)
    if not term:
        return None
    res = await asyncio.to_thread(wiki_source.lookup, term)
    if not res:
        return None
    extract, url = res
    return ("СПРАВКА ПО ВИДУ (Wikipedia, CC BY-SA — если используешь для описания биологии/"
            f"морфологии, кратко сошлись на источник: {url}). Не копируй дословно, перескажи:\n"
            f"{extract}")


async def _assemble(question: str, context: str | None = None,
                    history: str | None = None, structured: bool = False):
    """Ground the question (CropWise field data + Госкаталог products + literature) and
    assemble the (system, user_text, max_tokens) triple. Shared by the blocking answer()
    and the streaming path so both reason over the exact same context."""
    # Follow-ups («предложите варианты», «а норма?») carry the crop/target in the PREVIOUS turn —
    # fold the last user question from history into the grounding query so products still resolve.
    ground_q = question
    if history:
        prev_qs = re.findall(r"Пользователь:\s*(.+)", history)
        if prev_qs:
            ground_q = f"{prev_qs[-1].strip()}. {question}"
    # Extract crop+target once, then run the (independent) grounding lookups concurrently so
    # wall-time is the slowest one, not their sum — Госкаталог (DB), CyberLeninka (DB) and
    # Wikipedia (network) no longer stack.
    ct = await _extract_ct(ground_q)
    grounding, literature, wiki = await asyncio.gather(
        _registry_grounding(ground_q, ct),
        _literature_grounding(ground_q),
        _wikipedia_grounding(ground_q, ct),
    )
    epv = _epv_grounding(ground_q)          # farm's own ЭПВ thresholds (owned, authoritative)
    parts = [p for p in (
        f"ДАННЫЕ ПО ПОЛЮ:\n{context}" if context else None,
        (f"ПРЕДЫДУЩИЙ ДИАЛОГ (контекст для уточняющих вопросов и расчётов; "
         f"опирайся на него, если вопрос ссылается на «предыдущий ответ»):\n{history}"
         if history else None),
        epv,
        grounding,
        literature,
        wiki,
        f"ВОПРОС: {question}",
    ) if p]
    # Structured answer for real recommendation questions (grounding fired); conversational
    # otherwise (bot how-to, field history, off-topic).
    if structured:                                    # «Что это?» scan → always one icon layout
        sys, max_toks = _SCAN_SYS, 950
    else:
        sys, max_toks = (_REC_SYS, 950) if grounding else (_SYS, 900)
    return sys, "\n\n".join(parts), max_toks


async def assemble_prompt(question: str, context: str | None = None,
                          history: str | None = None, structured: bool = False):
    """Public: (system, user_text, max_tokens) for streaming, or None if the LLM is off.
    structured=True forces the «Что это?» icon layout regardless of grounding."""
    if not (settings.yc_api_key and settings.yc_folder_id):
        return None
    return await _assemble(question, context, history, structured)


def stream_complete(system_text: str, user_text: str, max_tokens: int, temperature: float = 0.3):
    """Public: sync generator yielding answer text deltas (for a StreamingResponse)."""
    return _complete_stream(system_text, user_text, max_tokens, temperature)


async def answer(question: str, context: str | None = None,
                 history: str | None = None) -> str | None:
    if not (settings.yc_api_key and settings.yc_folder_id):
        return None
    sys, user_text, max_toks = await _assemble(question, context, history)
    try:
        return await asyncio.to_thread(_complete, sys, user_text, max_toks, 0.3)
    except Exception:
        return None
