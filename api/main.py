"""Public web API for the flagleaf.ru AI agronomist (Phase 1).

A thin HTTP layer over the SAME brain the Telegram bot uses — no agronomy logic here:
- POST /api/chat      text question      → grounded, structured answer (agro_chat)
- POST /api/diagnose  photo + question   → structured photo diagnosis (diagnose)
- POST /api/feedback  thumbs up/down     → recorded for answer-quality learning

No field data and no secrets exposed; the only DB write is anonymous answer feedback. Open
demo, rate-limited per IP (LLM calls cost money). Runs as the `api` container on the bot VM,
bound to localhost; nginx terminates TLS for ai.flagleaf.ru and proxies here. See
docs/web-phase1-spec.md.
"""
import logging

import redis.asyncio as aioredis
from fastapi import FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import text as sql_text

from bot.agro_chat import answer as agro_answer
from bot.config import settings
from bot.db import engine
from bot.diagnose import diagnose as diagnose_photo
from bot.transcribe import transcribe_lpcm

logger = logging.getLogger("api")

app = FastAPI(title="Flagleaf AI API", version="1.0.0")

# Only our own web origins may call this from a browser.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://ai.flagleaf.ru", "https://flagleaf.ru", "https://www.flagleaf.ru"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

_redis = aioredis.from_url(settings.redis_url, decode_responses=True)

MAX_Q = 2000                  # chars
MAX_IMG = 12 * 1024 * 1024    # 12 MB
CHAT_PER_HOUR = 30
DIAG_PER_HOUR = 8


def _client_ip(req: Request) -> str:
    fwd = req.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() if fwd else (req.client.host if req.client else "unknown")


async def _rate_ok(ip: str, kind: str, limit: int, window: int = 3600) -> bool:
    """Per-IP cap: INCR a TTL key. Best-effort — allow on Redis failure."""
    key = f"flagleaf:web:{kind}:{ip}"
    try:
        n = await _redis.incr(key)
        if n == 1:
            await _redis.expire(key, window)
        return n <= limit
    except Exception:
        logger.warning("rate-limit redis unavailable — allowing")
        return True


class Turn(BaseModel):
    role: str                       # 'user' | 'bot'
    text: str


class ChatIn(BaseModel):
    question: str
    crop: str | None = None
    history: list[Turn] | None = None
    session: str | None = None


class FeedbackIn(BaseModel):
    vote: str                       # 'up' | 'down'
    crop: str | None = None
    question: str | None = None
    answer: str | None = None
    note: str | None = None


def _format_history(turns: list[Turn] | None) -> str | None:
    """Last few turns as a compact transcript for follow-up context (norms, «а если…»)."""
    if not turns:
        return None
    lines = []
    for t in turns[-6:]:
        who = "Пользователь" if t.role == "user" else "Ассистент"
        txt = (t.text or "").strip()
        if txt:
            lines.append(f"{who}: {txt[:1500]}")
    blob = "\n".join(lines)
    return blob[-4000:] if blob else None


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.post("/api/chat")
async def chat(body: ChatIn, request: Request):
    q = (body.question or "").strip()
    if not q:
        raise HTTPException(400, "empty question")
    if len(q) > MAX_Q:
        raise HTTPException(413, "question too long")
    if not await _rate_ok(_client_ip(request), "chat", CHAT_PER_HOUR):
        raise HTTPException(429, "Слишком много запросов. Попробуйте позже.")
    crop = (body.crop or "").strip()
    full_q = f"Культура: {crop}. {q}" if crop else q   # give the grounding the crop context
    ans = await agro_answer(full_q, history=_format_history(body.history))
    return {"answer": ans or "Не понял вопрос — переформулируйте, пожалуйста."}


@app.post("/api/diagnose")
async def diagnose(request: Request, image: UploadFile, question: str = Form(""),
                   crop: str = Form("")):
    img = await image.read()
    if not img:
        raise HTTPException(400, "empty image")
    if len(img) > MAX_IMG:
        raise HTTPException(413, "image too large")
    if not await _rate_ok(_client_ip(request), "diag", DIAG_PER_HOUR):
        raise HTTPException(429, "Слишком много фото-запросов. Попробуйте позже.")
    ans = await diagnose_photo(img, question.strip() or None, crop.strip() or None, None)
    return {"answer": ans or (
        "Не удалось обработать фото автоматически (возможно, временный сбой распознавания). "
        "Опишите проблему словами — какая культура, после какой обработки, какие симптомы — "
        "и я отвечу по описанию. Либо повторите попытку через минуту.")}


@app.post("/api/feedback")
async def feedback(body: FeedbackIn, request: Request):
    vote = (body.vote or "").strip()
    if vote not in ("up", "down"):
        raise HTTPException(400, "bad vote")
    # generous cap just to stop abuse; never block the UI on it
    if not await _rate_ok(_client_ip(request), "fb", 120):
        return {"ok": True}
    try:
        async with engine.begin() as conn:
            await conn.execute(
                sql_text("INSERT INTO web_feedback (vote, crop, question, answer, note, ip) "
                         "VALUES (:v, :c, :q, :a, :n, :ip)"),
                {"v": vote, "c": (body.crop or "")[:120] or None,
                 "q": (body.question or "")[:2000] or None,
                 "a": (body.answer or "")[:8000] or None,
                 "n": (body.note or "")[:1000] or None, "ip": _client_ip(request)})
    except Exception:
        logger.exception("feedback insert failed")
    return {"ok": True}


@app.post("/api/transcribe")
async def transcribe_ep(request: Request):
    """Web mic → text. Body is raw 16-bit mono LPCM @16 kHz (made by the browser's
    Web Audio API; SpeechKit transcribes it)."""
    audio = await request.body()
    if not audio:
        raise HTTPException(400, "empty audio")
    if len(audio) > 4 * 1024 * 1024:        # ~2 min of 16k mono PCM
        raise HTTPException(413, "audio too long")
    if not await _rate_ok(_client_ip(request), "stt", 40):
        raise HTTPException(429, "Слишком много запросов. Попробуйте позже.")
    try:
        text = await transcribe_lpcm(audio)
    except Exception:
        logger.exception("web transcribe failed")
        text = ""
    return {"text": text}
