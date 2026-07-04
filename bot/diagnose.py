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
from io import BytesIO

import requests
from PIL import Image, ImageOps

from bot.agro_chat import _complete, _literature_grounding, _registry_grounding
from bot.config import settings

logger = logging.getLogger("bot.diagnose")

_QWEN_URL = "https://llm.api.cloud.yandex.net/v1/chat/completions"
_QWEN_MODEL = "qwen3.6-35b-a3b"

_VISION_SYS = (
    # qwen3.6 is a reasoning model; without this it can ramble 10k+ tokens of hidden reasoning
    # and never emit the answer (finish=length, empty content). A hard brevity instruction cuts
    # reasoning ~10× (verified: 36k→2.8k chars, 58s→3s) — /no_think and reasoning_effort do NOT
    # work on Yandex, this prompt directive is what bounds it.
    "Отвечай БЫСТРО: рассуждай не более 1–2 коротких шагов и СРАЗУ выведи JSON — без длинных "
    "размышлений, без повторов.\n"
    "На фото — растение или проблема с поля (Центрально-Чернозёмный регион, Белгородская "
    "область). Определи объект как агроном и верни ТОЛЬКО JSON без пояснений:\n"
    '{"diagnosis":"русское название","latin":"Latin name или null",'
    '"category":"сорняк|болезнь|вредитель|иное",'
    '"confidence":число 0-100,'
    '"phase":"фаза развития, напр. 2-4 листа, или null",'
    '"symptoms":["видимый признак", ...],'
    '"differential":[{"name":"альтернативный вариант","why":"чем отличается"}],'
    '"weed_class":"двудольный|злаковый|null"}\n'
    "Учитывай и НЕинфекционные причины — на полях они частые: повреждение гербицидом/"
    "пестицидом после обработки (краевой ожог и пожелтение листьев, хлороз, скручивание, "
    "деформация точки роста), дефицит элементов питания, погодный/почвенный стресс. Если на "
    "фото сама КУЛЬТУРА с такими симптомами (а не сорняк/болезнь) — так и скажи (category "
    "«иное», diagnosis типа «повреждение гербицидом» / «дефицит питания»).\n"
    "РАЗЛИЧЕНИЕ ЧАСТЫХ ДВУДОЛЬНЫХ ВСХОДОВ (их легко перепутать — смотри признаки):\n"
    "• МАРЬ БЕЛАЯ (Chenopodium album) — мучнистый беловато-серый налёт (как мука/пыль) на "
    "молодых листьях и верхушке; листья ромбовидно-треугольные с неровным краем; стебель и "
    "пазухи часто с красноватыми/розовыми полосами.\n"
    "• ЩИРИЦА (Amaranthus retroflexus) — БЕЗ мучнистого налёта, лист гладкий; листья яйцевидно-"
    "ромбические с лёгкой выемкой на кончике; стебель опушённый; основание/корень розово-красные.\n"
    "• АМБРОЗИЯ — листья глубоко рассечённые, перистые (не цельные).\n"
    "Налёт-«мука» на листьях = почти наверняка марь, а не щирица. Если различить уверенно "
    "нельзя — поставь более вероятный вид, но ОБЯЗАТЕЛЬНО укажи альтернативу в differential и "
    "снизь confidence (≤60).\n"
    "Будь честен с уверенностью: всходы и злаковые трудно различить по фото — не завышай."
)


def _prep_image(img: bytes, max_side: int = 1536) -> bytes:
    """Downscale + re-encode to JPEG so the vision payload stays within the model's image
    limits — full-res phone photos uploaded via the web were rejected with HTTP 400 (the
    Telegram path works because Telegram pre-compresses). Also normalises EXIF orientation
    and HEIC/PNG/RGBA → RGB. Best-effort: returns the original bytes if anything fails."""
    try:
        im = Image.open(BytesIO(img))
        im = ImageOps.exif_transpose(im)
        if im.mode != "RGB":
            im = im.convert("RGB")
        im.thumbnail((max_side, max_side))
        out = BytesIO()
        im.save(out, format="JPEG", quality=85, optimize=True)
        return out.getvalue()
    except Exception:
        logger.warning("diagnose: image prep failed, sending original bytes", exc_info=True)
        return img

_DIAG_SYS = (
    "Ты — опытный агроном-консультант хозяйства «New Grain Co» (ЦЧР). По фото уже выполнено "
    "распознавание (блок РАСПОЗНАВАНИЕ). Составь ЧЁТКИЙ структурированный ответ агроному на "
    "русском, без воды, обычным текстом БЕЗ markdown-звёздочек. ФОРМАТ зависит от того, СОРНЯК "
    "это или нет.\n\n"
    "➤ ЕСЛИ СОРНЯК (category=сорняк): веди ответ от ТИПА сорняка — по фото он надёжен и именно "
    "он определяет выбор гербицида; точный ВИД часто неотличим по фото и потому второстепенен. "
    "Заголовки:\n"
    "🌿 Тип сорняка: <двудольный/злаковый> (по фото определяется надёжно; от него зависит выбор "
    "препарата).\n"
    "🔍 Предположительно вид: <вид>, возможно <альтернатива из differential> — точный вид "
    "подтвердит агроном (отличие: <ключевой признак, напр. мучнистый беловатый налёт → марь "
    "белая; без налёта, опушение и розовое основание → щирица>). НЕ настаивай на одном виде.\n"
    "👁 Что видно на фото: коротко.\n"
    "🛡 Чем обработать: 1) агротехнически; 2) химически — препараты ТОЛЬКО из блока "
    "зарегистрированных (для культуры + типа сорняка), с нормами и производителем. Если культура "
    "не указана — попроси уточнить.\n"
    "⏱ Когда обрабатывать: по фазе сорняка/культуры.\n\n"
    "➤ ИНАЧЕ (болезнь/вредитель/повреждение/иное):\n"
    "🔬 Диагноз: <название>; если есть differential — «вероятно X, но возможна Y» + отличительный "
    "признак. Это ориентир, окончательно определяет агроном.\n"
    "📊 Уверенность: <число>%.\n"
    "👁 Что видно на фото: коротко.\n"
    "❓ Что ещё это может быть: из differential, чем отличается.\n"
    "🔎 Проверить в поле: 2–4 быстрые проверки.\n"
    "🛡 Меры борьбы: 1) агротехнически; 2) химически.\n"
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


def _vision_call(frames: list[bytes], intro: str = "") -> dict | None:
    """Vision (qwen) identify — one image, or several frames of the SAME subject pulled from a
    video, sent together so the model reasons across them. `intro` prepends video context."""
    if not (settings.yc_api_key and settings.yc_folder_id):
        return None
    content = [{"type": "text", "text": (intro + "\n" if intro else "") + _VISION_SYS}]
    for fr in frames[:5]:
        img = _prep_image(fr)
        content.append({"type": "image_url",
                        "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(img).decode()}})
    body = {
        "model": f"gpt://{settings.yc_folder_id}/{_QWEN_MODEL}/latest",
        "messages": [{"role": "user", "content": content}],
        # The brevity directive in _VISION_SYS bounds reasoning to ~1k tokens, so this ceiling
        # is just a safety net (a truncated reasoning = finish=length + empty content → None).
        "temperature": 0, "max_tokens": 8000,
    }
    for attempt in (1, 2):  # one gentle retry — qwen vision throttles intermittently
        try:
            r = requests.post(_QWEN_URL,
                              headers={"Authorization": f"Api-Key {settings.yc_api_key}"},
                              json=body, timeout=150)
            if r.status_code != 200:
                logger.warning("diagnose vision HTTP %s (attempt %s)", r.status_code, attempt)
                if r.status_code in (429, 500, 502, 503) and attempt == 1:
                    continue
                return None
            choice = r.json()["choices"][0]
            msg = choice["message"]
            raw = msg.get("content") or msg.get("reasoning_content") or ""
            s = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
            brace = s.find("{")
            if brace >= 0:
                try:  # raw_decode: first complete object, tolerate trailing text
                    return json.JSONDecoder().raw_decode(s[brace:])[0]
                except json.JSONDecodeError:
                    pass
            logger.warning("diagnose vision: no JSON parsed (finish=%s, content=%d, reasoning=%d)",
                           choice.get("finish_reason"), len(msg.get("content") or ""),
                           len(msg.get("reasoning_content") or ""))
            return None
        except Exception:
            logger.exception("diagnose vision failed (attempt %s)", attempt)
            if attempt == 1:
                continue
            return None
    return None


def _vision_sync(img: bytes) -> dict | None:
    """Single-image identify (photo path / scan recognition)."""
    return _vision_call([img])


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


async def _compose(vd: dict, question: str | None, crop: str | None,
                   field_name: str | None, extra_ctx: str | None = None) -> str | None:
    """Turn a vision result (vd) into the grounded, structured answer. Shared by the photo
    and video paths. `extra_ctx` carries anything extra (e.g. a video's voice narration)."""
    # qwen is ~coin-flip on lookalike broadleaf seedlings (марь↔щирица↔амброзия, even weed↔crop)
    # yet stays overconfident. When it itself lists an alternative, that's its own uncertainty
    # signal — temper the DISPLAYED confidence so the answer reads as a hedged suggestion.
    if vd.get("differential"):
        try:
            if int(vd.get("confidence") or 0) > 60:
                vd["confidence"] = 60
        except (TypeError, ValueError):
            pass
    target = str(vd["diagnosis"])
    # For WEEDS the species is unreliable but the CLASS (двудольный/злаковый) is not — and the
    # class + crop is what actually drives the registered-product list. Ground on the class.
    wc = str(vd.get("weed_class") or "")
    cls = ("двудольных" if "двудол" in wc else "злаковых" if "злак" in wc else "")
    if str(vd.get("category")) == "сорняк" and cls:
        synth_q = (f"чем обработать {crop} от {cls} сорняков" if crop
                   else f"чем бороться с {cls} сорняками")
    else:
        synth_q = (f"чем обработать {crop} от {target}" if crop else f"чем бороться с {target}")
    grounding = await _registry_grounding(synth_q)
    literature = await _literature_grounding(f"{target} {crop or ''}")

    ctx = [f"ВОПРОС АГРОНОМА: {question or 'что это и как с этим бороться?'}",
           (f"КУЛЬТУРА (из карточки поля {field_name}): {crop}" if crop
            else "КУЛЬТУРА: не указана — попроси подтвердить."),
           "РАСПОЗНАВАНИЕ (по фото):\n" + _fmt_vision(vd)]
    if extra_ctx:
        ctx.append(extra_ctx)
    if grounding:
        ctx.append(grounding)
    if literature:
        ctx.append(literature)
    try:
        return await asyncio.to_thread(_complete, _DIAG_SYS, "\n\n".join(ctx), 1300, 0.4)
    except Exception:
        logger.exception("diagnose compose failed")
        return None


async def diagnose(img: bytes, question: str | None, crop: str | None,
                   field_name: str | None) -> str | None:
    """Structured diagnosis + grounded advice for a field photo. `crop`/`field_name` are
    the KNOWN field context (skip 'what crop?' when we have it). None on failure."""
    if not (settings.yc_api_key and settings.yc_folder_id):
        return None
    vd = await asyncio.to_thread(_vision_sync, img)
    if not vd or not vd.get("diagnosis"):
        return None
    return await _compose(vd, question, crop, field_name)


async def diagnose_video(frames: list[bytes], question: str | None, crop: str | None,
                         field_name: str | None, narration: str | None) -> str | None:
    """Comment on a short field video. The in-RU vision model reads STILLS, not motion — so we
    hand it the sharpest frames pulled from the clip and let it reason across them, and fold the
    voice narration (if any) into the answer. None on failure."""
    if not (settings.yc_api_key and settings.yc_folder_id) or not frames:
        return None
    vd = await asyncio.to_thread(
        _vision_call, frames,
        "Это НЕСКОЛЬКО КАДРОВ из одного короткого видео с поля (тот же участок). Определи объект "
        "по всем кадрам вместе; если на кадрах разные объекты — опиши главную проблему.")
    if not vd or not vd.get("diagnosis"):
        return None
    extra = (f"ГОЛОСОВОЙ КОММЕНТАРИЙ АГРОНОМА С ВИДЕО (расшифровка) — учитывай как описание "
             f"проблемы: «{narration.strip()}»") if narration and narration.strip() else None
    return await _compose(vd, question, crop, field_name, extra_ctx=extra)
