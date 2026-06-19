"""Public web API for the flagleaf.ru AI agronomist (Phase 1).

A thin HTTP layer over the SAME brain the Telegram bot uses — no agronomy logic here:
- POST /api/chat      text question      → grounded, structured answer (agro_chat)
- POST /api/diagnose  photo + question   → structured photo diagnosis (diagnose)

Read-only (no DB writes, no field data, no secrets exposed). Open demo, rate-limited per IP
(LLM calls cost money). Runs as the `api` container on the bot VM, bound to localhost; nginx
terminates TLS for ai.flagleaf.ru and proxies here. See docs/web-phase1-spec.md.
"""
import logging

import redis.asyncio as aioredis
from fastapi import FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from bot.agro_chat import answer as agro_answer
from bot.config import settings
from bot.diagnose import diagnose as diagnose_photo

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


class ChatIn(BaseModel):
    question: str
    session: str | None = None


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
    ans = await agro_answer(q)
    return {"answer": ans or "Не понял вопрос — переформулируйте, пожалуйста."}


@app.post("/api/diagnose")
async def diagnose(request: Request, image: UploadFile, question: str = Form("")):
    img = await image.read()
    if not img:
        raise HTTPException(400, "empty image")
    if len(img) > MAX_IMG:
        raise HTTPException(413, "image too large")
    if not await _rate_ok(_client_ip(request), "diag", DIAG_PER_HOUR):
        raise HTTPException(429, "Слишком много фото-запросов. Попробуйте позже.")
    ans = await diagnose_photo(img, question.strip() or None, None, None)
    return {"answer": ans or (
        "Не смог уверенно распознать по фото. Пришлите более чёткий снимок "
        "(всё растение + крупный план листа).")}
