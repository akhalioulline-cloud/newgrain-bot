"""Flagleaf — the platform-agnostic AI agronomist.

ONE entry point: `respond(ctx)`. Any surface — the Ear web feed, the Telegram bot, the future
native app — builds a Context and calls this. Flagleaf owns ALL of the agronomy orchestration
(field routing, photo/video recognition, grounding, thread field-resolution). It knows nothing
about any chat's storage, users, or transport — so Ear can run without Flagleaf, and Flagleaf
can run inside Telegram without Ear. They meet only at this contract.
"""
import asyncio
import logging
import re
from dataclasses import dataclass

from bot.agro_chat import answer as _agro_answer
from bot.agro_chat import _complete as _yc_complete
from bot.agro_chat import _clean_json
from bot.diagnose import diagnose as _diagnose_photo
from bot.diagnose import diagnose_video as _diagnose_video
from bot.field_plan import generate_field_plan
from bot.db import field_card_text
from bot.video_frames import extract_frames
from bot.video_transcribe import transcribe_video

logger = logging.getLogger("bot.flagleaf")


@dataclass
class Context:
    """What a surface hands Flagleaf about the current turn. Any subset may be set."""
    text: str | None = None        # the message (a question or an observation)
    image: bytes | None = None     # a photo to read
    video: bytes | None = None     # a video to read (Flagleaf extracts frames + narration)
    crop: str | None = None        # crop context, if the surface knows it
    field_hint: str | None = None  # the conversation's field (name/number), for «это поле»
    history: str | None = None     # prior conversation as a plain transcript


# ── being addressed («бот …») — Flagleaf decides when it's spoken to ──────────────
_ADDR_RE = re.compile(r"^\s*(бот|bot|флаглиф|flagleaf)[\s,:!-]", re.I)
# @-mention of the bot anywhere in the message (the wall's summon, like @grok in X)
_MENTION_RE = re.compile(r"(?:^|\s)@(flagleaf|флаглиф|флаглаф|flag)\b", re.I)


def addressed(text: str) -> bool:
    return bool(_ADDR_RE.match(text or ""))


def mentions_bot(text: str) -> bool:
    """The wall summons Flagleaf with @flagleaf (or «бот …» for continuity)."""
    return bool(_MENTION_RE.search(text or "") or addressed(text or ""))


def strip_address(text: str) -> str:
    t = re.sub(r"^\s*(бот|bot|флаглиф|flagleaf)[\s,:!-]+", "", text or "", flags=re.I)
    t = _MENTION_RE.sub(" ", t).strip()
    return t or (text or "")


# ── proactive (unsummoned) evaluation — SHADOW MODE: judges but does not post ──────
_SHADOW_SYSTEM = (
    "Ты — Флаглиф, ИИ-агроном в рабочем чате команды хозяйства, молчаливый наблюдатель. "
    "Тебя НЕ звали. Вставить короткую реплику стоит ТОЛЬКО если ты можешь добавить одну "
    "конкретную, проверяемую агрономическую пользу: поправить фактическую ошибку про препарат, "
    "дозу, норму расхода, регламент, действующее вещество, порог ЭПВ, культуру или "
    "севооборотное ограничение; либо назвать точный такой факт, которого в разговоре не хватает. "
    "НЕ реагируй на болтовню, приветствия, мнения, организационные вопросы, общие рассуждения "
    "и на то, что и так сказано верно. Банальность хуже молчания. Сомневаешься — молчи. "
    "Ответь СТРОГО в JSON без пояснений: "
    '{"speak": true|false, "confidence": 0.0-1.0, "line": "одна фраза ≤160 символов, по делу"}. '
    'Если speak=false — line оставь пустым.'
)


async def evaluate_proactive(text: str, history: str | None):
    """Would Flagleaf usefully chime in on this unsummoned message? Returns {confidence, line}
    if yes, else None. SHADOW MODE only calls this to LOG the would-be reply — nothing is posted."""
    msg = (text or "").strip()
    if len(msg) < 15:                      # skip trivial chatter ("ок", "спасибо")
        return None
    user = (f"Недавняя переписка:\n{history}\n\n" if history else "") + \
        f"Новое сообщение команды: «{msg}»\n\nСтоит ли вставить реплику?"
    try:
        raw = await asyncio.to_thread(_yc_complete, _SHADOW_SYSTEM, user, 220, 0.2)
        data = _clean_json(raw)
    except Exception:
        logger.exception("shadow proactive eval failed")
        return None
    if not isinstance(data, dict) or not data.get("speak"):
        return None
    line = (data.get("line") or "").strip()
    if not line:
        return None
    try:
        conf = float(data.get("confidence") or 0)
    except (TypeError, ValueError):
        conf = 0.0
    return {"confidence": conf, "line": line[:400]}


# ── field routing (moved here from the api layer; owned by Flagleaf now) ──────────
_FIELD_REF_RE = re.compile(r"пол[еяю]\s*№?\s*(\d+[а-я]?(?:\s*/\s*\d+)?)", re.I)
_PLAN_RE = re.compile(r"\bплан|работ\w*\s+по\s+пол", re.I)


def _field_ref(q: str):
    m = _FIELD_REF_RE.search((q or "").replace("ё", "е"))
    return re.sub(r"\s+", "", m.group(1)) if m else None


async def _field_route(q: str):
    """(plan_or_none, field_context_or_none) for a field question. plan is a ready answer to
    return verbatim; field_context is the field card to ground the LLM answer."""
    ref = _field_ref(q)
    if not ref:
        return None, None
    if _PLAN_RE.search(q):
        try:
            return await generate_field_plan(ref, None), None
        except Exception:
            logger.exception("field plan failed")
            return None, None
    try:
        return None, await field_card_text(ref, None)
    except Exception:
        logger.exception("field card failed")
        return None, None


def _crop_q(txt: str, crop: str) -> str:
    return f"Культура: {crop}. {txt}" if crop else txt


async def _safe_card(ref: str):
    try:
        return await field_card_text(ref, None)
    except Exception:
        return None


# ── the one entry point ───────────────────────────────────────────────────────────
async def respond(ctx: Context) -> str | None:
    """Flagleaf's reply for this turn, or None if it has nothing to add. Never touches storage."""
    # a photo to read
    if ctx.image is not None:
        try:
            return await _diagnose_photo(ctx.image, ctx.text or None, ctx.crop or None, None)
        except Exception:
            logger.exception("photo respond failed")
            return None
    # a video to read — Flagleaf owns frame extraction + narration transcription
    if ctx.video is not None:
        try:
            frames = await asyncio.to_thread(extract_frames, ctx.video)
            if not frames:
                return None
            narration = ""
            try:
                narration = await asyncio.to_thread(transcribe_video, ctx.video)
            except Exception:
                pass
            return await _diagnose_video(frames, ctx.text or None, ctx.crop or None, None, narration or None)
        except Exception:
            logger.exception("video respond failed")
            return None
    # text — field routing (plan / field card) → grounded answer; resolve the field from the
    # message, the surface's hint, or the thread history
    q = (ctx.text or "").strip()
    if not q:
        return None
    try:
        plan, field_ctx = await _field_route(q)
        if plan:
            return plan
        if not field_ctx and ctx.field_hint:
            field_ctx = await _safe_card(ctx.field_hint)
        if not field_ctx and ctx.history:
            ref = _field_ref(ctx.history)
            if ref:
                field_ctx = await _safe_card(ref)
        return await _agro_answer(_crop_q(q, ctx.crop or ""), context=field_ctx, history=ctx.history)
    except Exception:
        logger.exception("text respond failed")
        return None
