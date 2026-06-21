"""Public web API for the flagleaf.ru AI agronomist (Phase 1).

A thin HTTP layer over the SAME brain the Telegram bot uses — no agronomy logic here:
- POST /api/chat      text question      → grounded, structured answer (agro_chat)
- POST /api/diagnose  photo + question   → structured photo diagnosis (diagnose)
- POST /api/transcribe  mic audio (LPCM) → text (SpeechKit)
- POST /api/feedback  thumbs up/down     → recorded for answer-quality learning
- POST /api/contact   «связаться» form   → stored + pushed to ADMIN_TG_IDS

No field data and no secrets exposed; the only DB write is anonymous answer feedback. Open
demo, rate-limited per IP (LLM calls cost money). Runs as the `api` container on the bot VM,
bound to localhost; nginx terminates TLS for ai.flagleaf.ru and proxies here. See
docs/web-phase1-spec.md.
"""
import asyncio
import hashlib
import logging
import secrets
from datetime import date
from io import BytesIO
from uuid import uuid4

import redis.asyncio as aioredis
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image
from pydantic import BaseModel
from sqlalchemy import text as sql_text

from bot.agro_chat import answer as agro_answer
from bot.config import settings
from bot.db import (
    create_submission,
    engine,
    find_duplicate_submission,
    get_active_user,
    get_chief_agronomists,
    get_pilot_fields,
    update_submission,
)
from bot.diagnose import diagnose as diagnose_photo
from bot.storage import upload_bytes
from bot.transcribe import transcribe_lpcm
from labeling import alert

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


class ContactIn(BaseModel):
    name: str | None = None
    phone: str
    message: str | None = None


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


# ── Authenticated surface (web photo upload for labeling, Phase 2) ──────────────
# Login = a one-time 6-digit code the Telegram bot issues via /weblogin (Redis, 5-min TTL),
# exchanged here for a 30-day session token tied to the agronomist's users record.
SESSION_TTL = 30 * 24 * 3600


class AuthIn(BaseModel):
    code: str


@app.post("/api/auth/verify")
async def auth_verify(body: AuthIn):
    code = (body.code or "").strip()
    if not (code.isdigit() and len(code) == 6):
        raise HTTPException(400, "Код должен состоять из 6 цифр.")
    tg = await _redis.get(f"flagleaf:weblogin:{code}")
    if not tg:
        raise HTTPException(401, "Код неверный или истёк. Получите новый в боте командой /weblogin.")
    await _redis.delete(f"flagleaf:weblogin:{code}")           # one-time use
    user = await get_active_user(int(tg))
    if not user:
        raise HTTPException(403, "Нет доступа.")
    token = secrets.token_urlsafe(24)
    await _redis.set(f"flagleaf:session:{token}", str(user["tg_user_id"]), ex=SESSION_TTL)
    return {"token": token, "name": user["full_name"], "role": user["role"]}


async def require_user(request: Request):
    token = request.headers.get("x-session", "")
    tg = await _redis.get(f"flagleaf:session:{token}") if token else None
    if not tg:
        raise HTTPException(401, "Не авторизованы — войдите заново.")
    user = await get_active_user(int(tg))
    if not user:
        raise HTTPException(403, "Нет доступа.")
    return user


@app.get("/api/me")
async def me(user=Depends(require_user)):
    return {"name": user["full_name"], "role": user["role"], "farm_id": user["farm_id"]}


@app.get("/api/fields")
async def my_fields(user=Depends(require_user)):
    fs = await get_pilot_fields(user["farm_id"])
    return {"fields": [{"id": f["id"], "name": f["name"], "crop": f["crop"]} for f in fs]}


MAX_PHOTO = 25 * 1024 * 1024        # keep original-resolution phone photos


def _exif_gps(im):
    """(lat, lon) from EXIF GPS or (None, None). Telegram strips EXIF; web keeps it —
    that's a key reason to allow web upload (geo-tagged training photos)."""
    try:
        gps = im.getexif().get_ifd(0x8825)
        if not gps or 2 not in gps or 4 not in gps:
            return None, None
        dms = lambda v: float(v[0]) + float(v[1]) / 60 + float(v[2]) / 3600
        lat, lon = dms(gps[2]), dms(gps[4])
        if str(gps.get(1, "N")).upper().startswith("S"):
            lat = -lat
        if str(gps.get(3, "E")).upper().startswith("W"):
            lon = -lon
        return round(lat, 7), round(lon, 7)
    except Exception:
        return None, None


@app.post("/api/submit")
async def submit(user=Depends(require_user),
                 photos: list[UploadFile] = File(...),
                 field_id: str = Form(""), category: str = Form(""),
                 species: str = Form(""), comment: str = Form("")):
    """Web photo upload for the labeling pipeline — same destination as the Telegram flow
    (S3 + submissions), but keeps original resolution + EXIF GPS, and accepts many at once."""
    fid = int(field_id) if field_id.strip().isdigit() else None
    is_junior = user["role"] == "agronomist"          # plain agronomist → chief review
    status = "pending_review" if is_junior else "ready_for_labeling"
    saved, skipped, sids = 0, 0, []
    for ph in photos[:40]:
        img = await ph.read()
        if not img or len(img) > MAX_PHOTO:
            skipped += 1
            continue
        h = hashlib.sha256(img).hexdigest()
        if await find_duplicate_submission(user["id"], h):
            skipped += 1
            continue
        w = ht = lat = lon = None
        try:
            im = Image.open(BytesIO(img))
            w, ht = im.size
            lat, lon = _exif_gps(im)
        except Exception:
            pass
        sid = str(uuid4())
        ctype = ph.content_type or "image/jpeg"
        ext = "png" if "png" in ctype else "jpg"
        key = f"raw/{user['farm_id']}/{fid or 'other'}/{date.today():%Y-%m-%d}/{sid}.{ext}"
        try:
            url = await upload_bytes(key, img, ctype)
        except Exception:
            logger.exception("submit: S3 upload failed")
            skipped += 1
            continue
        await create_submission(sid, user["id"], fid, url, w, ht, h)
        upd = {"category": category.strip() or None, "subcategory": species.strip() or None,
               "comment_text": comment.strip() or None, "status": status}
        if lat is not None:
            upd.update(gps_lat=lat, gps_lon=lon, gps_source="exif")
        await update_submission(sid, **upd)
        saved += 1
        sids.append(sid)
    # Junior uploads → review cards to the chief agronomist(s), reusing the bot's flow.
    if is_junior and sids:
        try:
            cas = await get_chief_agronomists(user["farm_id"])
            if cas:
                from aiogram import Bot
                from aiogram.client.session.aiohttp import AiohttpSession
                from aiogram.client.telegram import TelegramAPIServer
                from bot.handlers import _send_review_card
                if settings.telegram_api_base:
                    server = TelegramAPIServer.from_base(settings.telegram_api_base.rstrip("/"))
                    rbot = Bot(settings.bot_token, session=AiohttpSession(api=server))
                else:
                    rbot = Bot(settings.bot_token)
                try:
                    for sid in sids:
                        for ca in cas:
                            await _send_review_card(rbot, ca["tg_user_id"], sid)
                finally:
                    await rbot.session.close()
        except Exception:
            logger.exception("submit: review-card delivery failed")
    return {"saved": saved, "skipped": skipped, "review": is_junior}


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


@app.post("/api/contact")
async def contact(body: ContactIn, request: Request):
    phone = (body.phone or "").strip()
    name = (body.name or "").strip()
    msg = (body.message or "").strip()
    if len(phone) < 5 or not any(c.isdigit() for c in phone):
        raise HTTPException(400, "нужен корректный телефон")
    if not await _rate_ok(_client_ip(request), "contact", 10):
        raise HTTPException(429, "Слишком много заявок. Попробуйте позже.")
    notified = False
    try:
        text = (f"📞 Заявка с ai.flagleaf.ru\nИмя: {name or '—'}\nТелефон: {phone}\n"
                f"Вопрос: {msg[:1000] or '—'}")
        notified = bool(await asyncio.to_thread(alert.send, text))
    except Exception:
        logger.exception("contact notify failed")
    try:
        async with engine.begin() as conn:
            await conn.execute(
                sql_text("INSERT INTO web_leads (name, phone, message, ip, notified) "
                         "VALUES (:n, :p, :m, :ip, :nf)"),
                {"n": name[:200] or None, "p": phone[:40],
                 "m": msg[:2000] or None, "ip": _client_ip(request), "nf": notified})
    except Exception:
        logger.exception("lead insert failed")
    return {"ok": True}
