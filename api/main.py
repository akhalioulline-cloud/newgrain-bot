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
import re
import secrets
from datetime import date
from io import BytesIO
from uuid import uuid4

import redis.asyncio as aioredis
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from PIL import Image
from pydantic import BaseModel
from sqlalchemy import text as sql_text

from bot.agro_chat import answer as agro_answer
from bot.agro_chat import assemble_prompt, stream_complete
from bot.config import settings
from bot.db import (
    add_push_subscription,
    count_pending_reviews,
    create_submission,
    create_video_job,
    engine,
    field_card_text,
    find_duplicate_submission,
    get_active_user,
    get_chief_agronomists,
    get_demo_fields,
    get_pending_reviews,
    get_pilot_fields,
    get_submission_review,
    get_team_progress,
    get_user_by_email,
    get_user_stats,
    get_user_uploads,
    update_submission,
    field_at_point,
    create_feed_post,
    add_feed_comment,
    set_feed_reaction,
    get_feed,
    get_feed_comments,
    get_feed_comments_bulk,
    get_feed_post,
    create_wall_message,
    get_wall,
    get_wall_message,
    recent_wall,
    set_wall_reaction,
    get_farm_members,
    mark_wall_seen,
    get_wall_overview,
    mark_dm_delivered,
    invite_user,
    log_shadow,
    get_shadow,
    shadow_stats,
    get_dm_peers,
    get_dm_messages,
    send_dm,
    get_farm_user,
    save_bot_chat,
    get_bot_chat,
    save_push_token,
    get_push_tokens,
    delete_push_token,
    get_submission_image_url,
)
from bot import flagleaf
from bot.flagleaf import _field_route      # Flagleaf owns field-routing now (also used by /api/chat)
from bot.diagnose import diagnose as diagnose_photo
from bot.diagnose import diagnose_video as diagnose_video_frames
from bot.diagnose import _vision_sync as _vision_recognize
from bot.video_frames import extract_frames
from bot.video_transcribe import transcribe_video
from bot.email_send import email_enabled, send_invite, send_login_code
from bot.field_plan import generate_field_plan
from bot.push import push_enabled, send_push
from bot.review_actions import approved_status, notify_submitter_decision
from bot.storage import download_bytes, presigned_get, upload_bytes
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
    structured: bool = False           # «Что это?» scan → force the consistent icon layout


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
SESSION_TTL = 90 * 24 * 3600


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


class EmailIn(BaseModel):
    email: str


@app.post("/api/auth/email/start")
async def auth_email_start(body: EmailIn, request: Request):
    """Email a 6-digit login code to a registered agronomist's address. The code lands
    in the SAME Redis slot /weblogin uses, so /api/auth/verify handles it unchanged.
    Tells the user when the address is unknown (private pilot tool — usability over
    anti-enumeration)."""
    if not email_enabled():
        raise HTTPException(503, "Вход по email пока недоступен. Получите код в Telegram-боте: /weblogin")
    email = (body.email or "").strip().lower()
    if "@" not in email or len(email) > 254:
        raise HTTPException(400, "Введите корректный email.")
    if not await _rate_ok(_client_ip(request), "emailcode", 5):
        raise HTTPException(429, "Слишком много запросов. Попробуйте позже.")
    user = await get_user_by_email(email)
    if not user:
        raise HTTPException(404, "Адрес не зарегистрирован. Добавьте его командой "
                                 "/myemail " + email + " в Telegram-боте Flagleaf.")
    code = f"{secrets.randbelow(900000) + 100000}"
    await _redis.set(f"flagleaf:weblogin:{code}", str(user["tg_user_id"]), ex=300)
    sent = await asyncio.to_thread(send_login_code, email, code)
    if not sent:
        await _redis.delete(f"flagleaf:weblogin:{code}")
        raise HTTPException(502, "Не удалось отправить письмо. Попробуйте Telegram-бот: /weblogin")
    return {"ok": True, "message": "Код отправлен на почту."}


async def require_user(request: Request):
    token = request.headers.get("x-session", "")
    tg = await _redis.get(f"flagleaf:session:{token}") if token else None
    if not tg:
        raise HTTPException(401, "Не авторизованы — войдите заново.")
    user = await get_active_user(int(tg))
    if not user:
        raise HTTPException(403, "Нет доступа.")
    return user


async def _optional_user(request: Request):
    """Like require_user but returns None instead of raising when there's no valid session —
    for endpoints that serve everyone yet do extra (store-for-learning) when signed in."""
    token = request.headers.get("x-session", "")
    tg = await _redis.get(f"flagleaf:session:{token}") if token else None
    if not tg:
        return None
    try:
        return await get_active_user(int(tg))
    except Exception:
        return None


@app.get("/api/me")
async def me(user=Depends(require_user)):
    return {"id": user["id"], "name": user["full_name"], "role": user["role"], "farm_id": user["farm_id"]}


# ── Web Push (PWA notifications) ─────────────────────────────────────────────────
@app.get("/api/push/key")
async def push_key():
    """VAPID public key the browser needs to subscribe (and whether push is on)."""
    return {"key": settings.vapid_public_key, "enabled": push_enabled()}


class PushSub(BaseModel):
    endpoint: str
    keys: dict


@app.post("/api/push/subscribe")
async def push_subscribe(body: PushSub, user=Depends(require_user)):
    await add_push_subscription(
        user["tg_user_id"], body.endpoint,
        body.keys.get("p256dh", ""), body.keys.get("auth", ""))
    return {"ok": True}


@app.post("/api/push/test")
async def push_test(user=Depends(require_user)):
    n = await send_push(user["tg_user_id"], "Flagleaf",
                        "Тестовое уведомление — всё работает 🎉", "/app/")
    return {"ok": True, "sent": n}


@app.get("/api/fields")
async def my_fields(user=Depends(require_user)):
    fs = await get_pilot_fields(user["farm_id"])
    return {"fields": [{"id": f["id"], "name": f["name"], "crop": f["crop"],
                        "demo": bool(f["is_demo"])} for f in fs]}


@app.get("/api/demo-fields")
async def demo_fields(user=Depends(require_user)):
    """Demonstration fields + days since last observed — drives the «контрольные поля» nudge."""
    fs = await get_demo_fields(user["farm_id"])
    return {"fields": [{"id": f["id"], "name": f["name"], "crop": f["crop"],
                        "last_days": f["last_days"]} for f in fs]}


class PlanIn(BaseModel):
    field: str


@app.post("/api/plan")
async def field_plan(body: PlanIn, user=Depends(require_user)):
    """Pilot v2: a treatment plan for a field (history + scouting + registered products),
    scoped to the agronomist's farm. Same engine as the bot's /plan."""
    q = (body.field or "").strip()
    if not q:
        raise HTTPException(400, "Укажите поле, например 121/140.")
    plan = await generate_field_plan(q, user["farm_id"], ran_by=user["tg_user_id"])
    return {"plan": plan}


@app.get("/api/stats")
async def my_stats(user=Depends(require_user)):
    """Personal contribution + the collective team goal (for the «ваш вклад» line)."""
    s = await get_user_stats(user["id"])
    collected, trained = await get_team_progress()
    return {
        "total": int(s["total"]), "week": int(s["week"]), "labeled": int(s["labeled"]),
        "team_collected": collected, "team_trained": trained,
        "team_goal": settings.team_photo_goal,
    }


@app.get("/api/my-uploads")
async def my_uploads(user=Depends(require_user)):
    """The caller's own recent uploads + status — so they can confirm in the app that
    what they sent actually landed on the server (не только тост «Загружено»)."""
    rows = await get_user_uploads(user["id"], 25)
    return {"uploads": [{
        "when": r["created_at"].isoformat() if r["created_at"] else None,
        "field": r["field_name"],
        "category": r["category"],
        "species": r["species_name"],
        "status": r["status"],
        "is_video": bool(r["is_video"]),
    } for r in rows]}


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
    annotatable = category.strip() in ("weed", "disease", "pest")   # only these need CVAT boxes
    review = is_junior and annotatable                # only weed/disease/pest go to chief review
    status = ("pending_review" if review else         # non-annotatable (scouting/control/…) → terminal,
              "ready_for_labeling" if annotatable else "stored")    # skips CVAT + the "awaiting" queue
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
    # Junior uploads (except scouting) → review cards to the chief agronomist(s).
    if review and sids:
        try:
            cas = await get_chief_agronomists(user["farm_id"])
            if cas:
                from bot.handlers import _send_review_card
                rbot = _relay_bot()
                try:
                    for sid in sids:
                        for ca in cas:
                            await _send_review_card(rbot, ca["tg_user_id"], sid)
                finally:
                    await rbot.session.close()
        except Exception:
            logger.exception("submit: review-card delivery failed")
    return {"saved": saved, "skipped": skipped, "review": review}


MAX_VIDEO = 400 * 1024 * 1024     # ~400 MB ceiling (covers ~3 min even at high quality)


async def _store_photo_submission(user, img: bytes, ctype: str, field_id, comment: str) -> str | None:
    """Persist one photo as a scouting learning record (S3 + submission, category=scouting →
    'stored'). Dedup by hash: a byte-identical re-upload reuses the EXISTING submission (so the
    feed post still shows the photo + gets a fresh reply) without creating a duplicate training
    row. Returns the submission id, or None only on a real storage failure."""
    h = hashlib.sha256(img).hexdigest()
    dup = await find_duplicate_submission(user["id"], h)
    if dup:
        return str(dup["id"])
    fid = int(field_id) if str(field_id).strip().isdigit() else None
    w = ht = lat = lon = None
    try:
        im = Image.open(BytesIO(img)); w, ht = im.size; lat, lon = _exif_gps(im)
    except Exception:
        pass
    sid = str(uuid4())
    ext = "png" if "png" in (ctype or "") else "jpg"
    key = f"raw/{user['farm_id']}/{fid or 'other'}/{date.today():%Y-%m-%d}/{sid}.{ext}"
    try:
        url = await upload_bytes(key, img, ctype or "image/jpeg")
    except Exception:
        logger.exception("feed: photo S3 upload failed")
        return None
    await create_submission(sid, user["id"], fid, url, w, ht, h)
    upd = {"category": "scouting", "comment_text": comment.strip() or None, "status": "stored"}
    if lat is not None:
        upd.update(gps_lat=lat, gps_lon=lon, gps_source="exif")
    await update_submission(sid, **upd)
    return sid


async def _store_scout_video(user, data: bytes, ctype: str, field_id, comment: str) -> str | None:
    """Persist a video as a scouting field-state record (S3 + submission + transcription job).
    Junior → pending_review (chief verifies); chief/admin → stored. Returns the submission id."""
    fid = int(field_id) if str(field_id).strip().isdigit() else None
    sid = str(uuid4())
    ctype = ctype or "video/mp4"
    ext = "mov" if "quicktime" in ctype else ("webm" if "webm" in ctype else "mp4")
    key = f"raw/{user['farm_id']}/{fid or 'other'}/{date.today():%Y-%m-%d}/scout-{sid}.{ext}"
    url = await upload_bytes(key, data, ctype)
    h = hashlib.sha256(data).hexdigest()
    review = user["role"] == "agronomist"   # juniors' videos wait for chief verification
    await create_submission(sid, user["id"], fid, url, None, None, h)
    await update_submission(sid, category="scouting",
                            status="pending_review" if review else "stored",
                            comment_text=(comment.strip() or None))
    await create_video_job(sid, key)
    return sid


@app.post("/api/scout-video")
async def scout_video(user=Depends(require_user),
                      video: UploadFile = File(...),
                      field_id: str = Form(""), comment: str = Form("")):
    """A scouting video (Pilot v2): stored as a field-state record; its voice narration is
    transcribed in the background (video_jobs → collector) into the field's observations.
    A junior's video waits for the chief agronomist's verification (Almas's request)."""
    data = await video.read()
    if not data:
        raise HTTPException(400, "Пустой файл.")
    if len(data) > MAX_VIDEO:
        raise HTTPException(413, "Видео слишком большое — снимите покороче (до ~3 минут).")
    try:
        sid = await _store_scout_video(user, data, video.content_type or "video/mp4",
                                       field_id, comment)
    except Exception:
        logger.exception("scout-video: store failed")
        raise HTTPException(502, "Не удалось сохранить видео. Попробуйте ещё раз.")
    return {"ok": True, "submission_id": sid}


# ─────────────────────────── Chief-agronomist review inbox ───────────────────────────
# Almas can now review photos and scouting videos in the app, not just via Telegram.
# The decision path is shared with the Telegram buttons (bot.review_actions) so the
# outcome and the submitter's notification are identical wherever he acts.

def _relay_bot():
    """An aiogram Bot for one-off sends from the api (review notices, cards). Routes
    through the Telegram API relay when configured, else straight to api.telegram.org.
    Caller must `await bot.session.close()`."""
    from aiogram import Bot
    from aiogram.client.session.aiohttp import AiohttpSession
    from aiogram.client.telegram import TelegramAPIServer
    if settings.telegram_api_base:
        server = TelegramAPIServer.from_base(settings.telegram_api_base.rstrip("/"))
        return Bot(settings.bot_token, session=AiohttpSession(api=server))
    return Bot(settings.bot_token)


def _require_chief(user):
    if user["role"] not in ("chief_agronomist", "admin"):
        raise HTTPException(403, "Только старший агроном проверяет материалы.")


@app.get("/api/review/count")
async def review_count(user=Depends(require_user)):
    """How many items await this chief's verification — for the review-tab badge."""
    if user["role"] not in ("chief_agronomist", "admin"):
        return {"count": 0}
    return {"count": await count_pending_reviews(user["farm_id"])}


@app.get("/api/review/pending")
async def review_pending(user=Depends(require_user)):
    """The review inbox: photos + scouting videos waiting for the chief's verification,
    each with a time-limited media link he can open right in the app."""
    _require_chief(user)
    rows = await get_pending_reviews(user["farm_id"])
    items = []
    for r in rows:
        try:
            media = presigned_get(r["image_url"], expires=7 * 24 * 3600)
        except Exception:
            logger.exception("review: presign failed for %s", r["id"])
            media = None
        items.append({
            "id": r["id"],
            "is_video": bool(r["is_video"]),
            "field_id": r["field_id"],
            "field_name": r["field_name"],
            "submitter": r["submitter"],
            "category": r["category"],
            "subcategory": r["subcategory"],
            "comment": r["comment_text"],
            "transcript": r["comment_voice_text"],
            "media_url": media,
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        })
    return {"items": items}


class ReviewDecision(BaseModel):
    submission_id: str
    action: str                      # "approve" | "reject"
    field_id: int | None = None      # optional corrections applied before finalizing
    category: str | None = None
    subcategory: str | None = None
    comment: str | None = None


@app.post("/api/review/decide")
async def review_decide(body: ReviewDecision, user=Depends(require_user)):
    """Approve or reject one item from the app — with optional inline corrections.
    Mirrors the Telegram review buttons exactly (same status routing + submitter notice)."""
    _require_chief(user)
    if body.action not in ("approve", "reject"):
        raise HTTPException(400, "Неизвестное действие.")
    sub = await get_submission_review(body.submission_id)
    if not sub:
        raise HTTPException(404, "Материал не найден.")
    if sub["status"] != "pending_review":
        return {"ok": True, "already": True}     # someone already handled it (Telegram/other chief)

    # Optional corrections first (so the final status reflects any category change).
    upd = {}
    if body.field_id is not None:
        upd["field_id"] = body.field_id
    if body.category:
        upd["category"] = body.category.strip()
    if body.subcategory is not None:
        upd["subcategory"] = body.subcategory.strip() or None
    if body.comment is not None:
        upd["comment_text"] = body.comment.strip() or None
    if upd:
        await update_submission(body.submission_id, **upd)
        sub = await get_submission_review(body.submission_id)

    new_status = approved_status(sub) if body.action == "approve" else "rejected"
    await update_submission(body.submission_id, status=new_status)

    rbot = _relay_bot()
    try:
        await notify_submitter_decision(rbot, sub, body.action)
    except Exception:
        logger.exception("review: submitter notify failed")
    finally:
        await rbot.session.close()
    return {"ok": True, "status": new_status}


class Geo(BaseModel):
    lat: float
    lon: float


@app.post("/api/field-at-point")
async def field_at_point_ep(body: Geo, user=Depends(require_user)):
    """Which field the agronomist is standing in (GPS → PostGIS), any field, farm-scoped."""
    f = await field_at_point(body.lat, body.lon, user["farm_id"])
    return {"field": {"id": f["id"], "name": f["name"], "crop": f["crop"]} if f else None}


# ─────────────────────────── Group feed (shared team wall) ───────────────────────────
FEED_PER_HOUR = 60


def _presign(url):
    try:
        return presigned_get(url, expires=7 * 24 * 3600) if url else None
    except Exception:
        return None


@app.get("/api/feed")
async def feed_list(user=Depends(require_user)):
    """The farm's shared feed (newest first): each post's author, media, field, bot reply count,
    comment count and reaction tallies + the viewer's own reaction."""
    rows = await get_feed(user["farm_id"], user["id"], 60)
    ids = [r["id"] for r in rows]
    threads = {}
    raw_thread = {}
    for c in await get_feed_comments_bulk(ids):
        raw_thread.setdefault(c["post_id"], []).append(c)
        threads.setdefault(c["post_id"], []).append({
            "id": c["id"], "is_bot": c["is_bot"],
            "author": ("Flagleaf" if c["is_bot"] else c["author"]),
            "chief": (not c["is_bot"]) and c["author_role"] in ("chief_agronomist", "admin"),
            "body": c["body"],
            "created_at": c["created_at"].isoformat() if c["created_at"] else None,
        })

    def _bot_follows(post_id, post_author_id):
        # would an un-prefixed reply by THIS viewer get a bot answer? (mirrors feed_comment's rule)
        thr = raw_thread.get(post_id, [])
        if not any(c["is_bot"] for c in thr):
            return False
        humans = {c["author_id"] for c in thr if not c["is_bot"] and c["author_id"] is not None}
        humans.add(user["id"])
        return humans <= {post_author_id}

    posts = [{
        "id": r["id"], "author": r["author"], "author_id": r["author_id"],
        "body": r["body"], "field": r["field_name"],
        "media": _presign(r["image_url"]), "is_video": bool(r["is_video"]),
        "thread": threads.get(r["id"], []),
        "bot_follows": _bot_follows(r["id"], r["author_id"]),
        "ups": r["ups"], "downs": r["downs"], "my_reaction": r["my_reaction"],
        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
    } for r in rows]
    return {"posts": posts, "me": {"id": user["id"], "role": user["role"], "name": user["full_name"]}}


@app.get("/api/feed/{post_id}/comments")
async def feed_comments_list(post_id: int, user=Depends(require_user)):
    rows = await get_feed_comments(post_id)
    return {"comments": [{
        "id": c["id"], "is_bot": c["is_bot"],
        "author": ("ИИ-агроном Flagleaf" if c["is_bot"] else c["author"]),
        "chief": (not c["is_bot"]) and c["author_role"] in ("chief_agronomist", "admin"),
        "body": c["body"],
        "created_at": c["created_at"].isoformat() if c["created_at"] else None,
    } for c in rows]}


@app.post("/api/feed/post")
async def feed_create(request: Request, user=Depends(require_user),
                      body: str = Form(""), field_id: str = Form(""), crop: str = Form(""),
                      image: UploadFile | None = File(None), video: UploadFile | None = File(None)):
    """Create a shared post — media (photo/video, filed as scouting for learning) and/or text.
    Ear stores the message, then asks its Flagleaf participant for a reply (if any)."""
    if not await _rate_ok(_client_ip(request), "feed", FEED_PER_HOUR):
        raise HTTPException(429, "Слишком много постов. Попробуйте позже.")
    txt = body.strip()
    fid = int(field_id) if field_id.strip().isdigit() else None
    cr = crop.strip() or None
    sub_id, ctx = None, None
    if image is not None:
        img = await image.read()
        if not img:
            raise HTTPException(400, "Фото не загрузилось. Попробуйте ещё раз.")
        if len(img) > MAX_IMG:
            raise HTTPException(413, "Фото слишком большое (макс. 12 МБ).")
        sub_id = await _store_photo_submission(user, img, image.content_type or "image/jpeg", field_id, txt)
        if sub_id is None:
            raise HTTPException(502, "Не удалось сохранить фото. Попробуйте ещё раз.")
        ctx = flagleaf.Context(image=img, text=txt or None, crop=cr)
    elif video is not None:
        data = await video.read()
        if not data:
            raise HTTPException(400, "Видео не загрузилось. Попробуйте ещё раз.")
        if len(data) > MAX_VIDEO_COMMENT:
            raise HTTPException(413, "Видео слишком большое (макс. 60 МБ). Снимите короче.")
        try:
            sub_id = await _store_scout_video(user, data, video.content_type or "video/mp4", field_id, txt)
        except Exception:
            logger.exception("feed: video store failed")
        ctx = flagleaf.Context(video=data, text=txt or None, crop=cr)
    elif txt:
        ctx = flagleaf.Context(text=txt, crop=cr)
    if not (sub_id or ctx or txt):
        raise HTTPException(400, "Пустой пост.")
    post_id = await create_feed_post(user["farm_id"], user["id"], sub_id, fid, txt or None)
    if ctx is not None:                              # Ear asks its Flagleaf participant
        reply = await flagleaf.respond(ctx)
        if reply:
            await add_feed_comment(post_id, None, True, reply)
    return {"ok": True, "post_id": post_id}


class FeedComment(BaseModel):
    body: str


@app.post("/api/feed/{post_id}/comment")
async def feed_comment(post_id: int, body: FeedComment, user=Depends(require_user)):
    """A discussion comment. Flagleaf stays silent (just learns) unless addressed («бот …»)."""
    txt = (body.body or "").strip()
    if not txt:
        raise HTTPException(400, "Пустой комментарий.")
    post = await get_feed_post(post_id)
    if not post:
        raise HTTPException(404, "Пост не найден.")
    prior = await get_feed_comments(post_id)          # thread BEFORE this comment
    await add_feed_comment(post_id, user["id"], False, txt)
    if post["author_id"] != user["id"]:
        _push_bg([post["author_id"]], f"{user['full_name']} — в ленте", txt)
    # The bot answers when called («бот …») — or as a natural follow-up while the thread is still
    # a private Q&A between the post's author and the bot. As soon as another teammate joins the
    # thread it becomes a human discussion and the bot goes quiet unless explicitly called. This
    # is robust to an unanswered human message in between (no "poisoned thread").
    bot_spoke = any(c["is_bot"] for c in prior)
    humans = {c["author_id"] for c in prior if not c["is_bot"] and c["author_id"] is not None}
    humans.add(user["id"])
    solo_with_bot = bot_spoke and humans <= {post["author_id"]}
    if flagleaf.addressed(txt) or solo_with_bot:
        # Ear owns the conversation: build the thread transcript + the thread's field, hand to Flagleaf
        hist = []
        if post["body"]:
            hist.append(f"{post['author']}: {post['body']}")
        for c in prior:
            who = "Flagleaf" if c["is_bot"] else (c["author"] or "агроном")
            b = (c["body"] or "").strip()
            if b:
                hist.append(f"{who}: {b[:1200]}")
        img = None
        if post["submission_id"] and not post["is_video"]:
            try:                                      # re-look at the post's photo, don't answer blind
                u = await get_submission_image_url(post["submission_id"])
                if u:
                    img = await download_bytes(u)
            except Exception:
                logger.exception("feed comment: photo re-fetch failed")
        reply = await flagleaf.respond(flagleaf.Context(
            image=img, text=flagleaf.strip_address(txt), crop=(post["crop"] or None),
            field_hint=(post["field_name"] or None), history="\n".join(hist)[-4000:] or None))
        if reply:
            await add_feed_comment(post_id, None, True, reply)
    return {"ok": True}


class FeedReact(BaseModel):
    verdict: str      # 'up' | 'down' | 'none'


@app.post("/api/feed/{post_id}/react")
async def feed_react(post_id: int, body: FeedReact, user=Depends(require_user)):
    """The chief's 👍/👎 — the ground-truth signal, and it drives the labeling gate: 👍 approves
    the post's submission (pending/rejected → into training), 👎 rejects it (out of training).
    Purely in-feed — no Telegram ping; the author sees the verdict in the feed."""
    _require_chief(user)
    v = body.verdict if body.verdict in ("up", "down", "none") else "none"
    await set_feed_reaction(post_id, user["id"], v)
    if v in ("up", "down"):
        post = await get_feed_post(post_id)
        if post and post["author_id"] != user["id"]:
            _push_bg([post["author_id"]], "Вердикт старшего",
                     ("✅ подтвердил: " if v == "up" else "❌ отклонил: ") + (post["body"] or "ваше наблюдение"))
        if post and post["submission_id"]:
            try:
                sub = await get_submission_review(post["submission_id"])
                if sub:
                    if v == "down" and sub["status"] != "rejected":
                        await update_submission(post["submission_id"], status="rejected")
                    elif v == "up" and sub["status"] in ("pending_review", "rejected"):
                        await update_submission(post["submission_id"], status=approved_status(sub))
            except Exception:
                logger.exception("feed react: submission status update failed")
    return {"ok": True}


# ── Self-hosted OTA updates (Expo Updates protocol; replaces eascdn after its 403s) ──
import json as _json
import os as _os
from uuid import uuid4 as _uuid4

_OTA_DIR = "/ota/dist"   # bind-mounted from /var/www/ai/updates/dist (published by scripts/publish_ota.py)


@app.get("/api/ota/manifest")
async def ota_manifest(request: Request):
    """Expo Updates v1 manifest endpoint. The app polls this on launch; assets themselves are
    served statically by nginx from /updates/dist/. multipart/mixed per protocol; when the
    client already runs the latest update → noUpdateAvailable directive."""
    platform = (request.headers.get("expo-platform") or "").lower()
    if platform not in ("android", "ios"):
        raise HTTPException(400, "expo-platform required")
    path = f"{_OTA_DIR}/manifest-{platform}.json"
    if not _os.path.exists(path):
        raise HTTPException(404, "no update published")
    with open(path) as f:
        manifest = _json.load(f)
    runtime = request.headers.get("expo-runtime-version") or ""
    current = (request.headers.get("expo-current-update-id") or "").lower()
    if current == manifest["id"].lower() or (runtime and runtime != manifest["runtimeVersion"]):
        name, payload = "directive", _json.dumps({"type": "noUpdateAvailable"})
    else:
        name, payload = "manifest", _json.dumps(manifest)
    boundary = _uuid4().hex
    body = (f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"\r\n'
            f"Content-Type: application/json\r\n\r\n"
            f"{payload}\r\n"
            f"--{boundary}--\r\n")
    return Response(content=body, media_type=f"multipart/mixed; boundary={boundary}",
                    headers={"expo-protocol-version": "1", "expo-sfv-version": "0",
                             "cache-control": "private, max-age=0"})


# ── Native push (Expo) — one token per device; delivery needs the EAS build ──────
class PushReg(BaseModel):
    token: str
    platform: str = ""


@app.post("/api/push/register")
async def push_register(body: PushReg, user=Depends(require_user)):
    tok = (body.token or "").strip()
    if not tok.startswith("ExponentPushToken"):
        raise HTTPException(400, "not an Expo push token")
    await save_push_token(user["id"], tok, (body.platform or "")[:20])
    return {"ok": True}


async def _push_notify(user_ids, title, body):
    """Fire-and-forget Expo push to all devices of the given users. Silently no-ops when
    nobody has registered a token (i.e., until the EAS build ships). Dead tokens are pruned."""
    try:
        tokens = await get_push_tokens(list(user_ids))
        if not tokens:
            return
        import aiohttp
        msgs = [{"to": t, "title": title, "body": (body or "")[:170], "sound": "default",
                 "channelId": "messages", "priority": "high", "badge": 1} for t in tokens]
        async with aiohttp.ClientSession() as s:
            async with s.post("https://exp.host/--/api/v2/push/send", json=msgs,
                              timeout=aiohttp.ClientTimeout(total=10)) as r:
                data = await r.json()
        for t, tick in zip(tokens, (data or {}).get("data", [])):
            if isinstance(tick, dict) and tick.get("details", {}).get("error") == "DeviceNotRegistered":
                await delete_push_token(t)
    except Exception:
        logger.exception("push send failed")


def _push_bg(user_ids, title, body):
    if user_ids:
        asyncio.create_task(_push_notify(user_ids, title, body))


# ── Team invites (admin/chief adds a member by email — no Telegram needed) ────────
class InviteIn(BaseModel):
    name: str
    email: str
    role: str = "agronomist"      # 'agronomist' | 'chief_agronomist' | 'admin'


@app.post("/api/invite")
async def invite(body: InviteIn, user=Depends(require_user)):
    _require_chief(user)
    name = (body.name or "").strip()
    email = (body.email or "").strip().lower()
    role = body.role if body.role in ("agronomist", "chief_agronomist", "admin") else "agronomist"
    if len(name) < 2:
        raise HTTPException(400, "Введите имя и фамилию.")
    if "@" not in email or "." not in email.rsplit("@", 1)[-1] or len(email) > 254:
        raise HTTPException(400, "Введите корректную почту.")
    if not email_enabled():
        raise HTTPException(503, "Почтовые приглашения пока недоступны.")
    uid, err = await invite_user(user["farm_id"], name, email, role)
    if err:
        raise HTTPException(409, err)
    sent = await asyncio.to_thread(send_invite, email, name, user["full_name"] or "Администратор")
    return {"ok": True, "user_id": uid, "email_sent": bool(sent)}


# ── Person-to-person DMs (agronomist ↔ agronomist, human-only) ───────────────────
class DmSend(BaseModel):
    body: str


@app.get("/api/dm/threads")
async def dm_threads(user=Depends(require_user)):
    """Teammates as chat rows: last message + unread count (whole farm — team is small)."""
    try:
        await mark_dm_delivered(user["id"])
    except Exception:
        logger.exception("mark delivered failed")
    rows = await get_dm_peers(user["farm_id"], user["id"])
    return {"peers": [
        {"id": r["id"], "name": r["name"], "role": r["role"],
         "last_body": r["last_body"], "last_at": r["last_at"].isoformat() if r["last_at"] else None,
         "last_mine": r["last_sender"] == user["id"] if r["last_sender"] is not None else False,
         "unread": r["unread"]}
        for r in rows]}


@app.get("/api/dm/with/{peer_id}")
async def dm_thread(peer_id: int, user=Depends(require_user)):
    peer = await get_farm_user(user["farm_id"], peer_id)
    if not peer:
        raise HTTPException(404, "Нет такого участника.")
    msgs = await get_dm_messages(user["id"], peer_id)
    return {"peer": {"id": peer["id"], "name": peer["full_name"], "role": peer["role"]},
            "messages": [{"id": m["id"], "mine": m["sender_id"] == user["id"], "body": m["body"],
                          "read": m["read_at"] is not None,
                          "delivered": m["delivered_at"] is not None,
                          "created_at": m["created_at"].isoformat()} for m in msgs]}


@app.post("/api/dm/with/{peer_id}")
async def dm_send(peer_id: int, body: DmSend, user=Depends(require_user)):
    txt = (body.body or "").strip()
    if not txt:
        raise HTTPException(400, "Пустое сообщение.")
    if len(txt) > 4000:
        raise HTTPException(413, "Слишком длинное сообщение.")
    peer = await get_farm_user(user["farm_id"], peer_id)
    if not peer:
        raise HTTPException(404, "Нет такого участника.")
    row = await send_dm(user["farm_id"], user["id"], peer_id, txt)
    _push_bg([peer_id], user["full_name"] or "Новое сообщение", txt)
    return {"ok": True, "id": row["id"], "created_at": row["created_at"].isoformat()}


# ── Team wall (single flat message stream; @flagleaf summons the bot, photos auto) ──
@app.get("/api/members")
async def members(user=Depends(require_user)):
    """Teammates for the @-mention picker + client-side highlight (excludes self)."""
    out = []
    for m in await get_farm_members(user["farm_id"]):
        if m["id"] == user["id"]:
            continue
        first = (m["full_name"] or "").split()[0] if m["full_name"] else ""
        out.append({"id": m["id"], "name": m["full_name"], "first": first, "role": m["role"]})
    return {"members": out}


def _mention_targets(txt, members, exclude_id):
    """user_ids @-mentioned by first name (best-effort; team is small)."""
    if not txt or "@" not in txt:
        return set()
    tokens = {t.lower() for t in re.findall(r"@([^\s@,.:;!?]+)", txt)}
    out = set()
    for m in members:
        if m["id"] == exclude_id:
            continue
        first = ((m["full_name"] or "").split()[0] if m["full_name"] else "").lower()
        if first and first in tokens:
            out.add(m["id"])
    return out


def _wall_history(rows):
    lines = []
    for r in rows:
        who = "Flagleaf" if r["is_bot"] else (r["author"] or "агроном")
        b = (r["body"] or "").strip()
        if b:
            lines.append(f"{who}: {b[:800]}")
    return "\n".join(lines)[-4000:] or None


async def _reply_photo_bytes(reply_msg):
    """The photo to re-show Flagleaf when a text @flagleaf / quote references it: the quoted
    message's own photo, or — if quoting the bot's answer — the photo that answer was about."""
    target = None
    if reply_msg:
        if reply_msg["submission_id"] and not reply_msg["is_video"]:
            target = reply_msg["submission_id"]
        elif reply_msg["is_bot"] and reply_msg.get("reply_to"):
            parent = await get_wall_message(reply_msg["reply_to"])
            if parent and parent["submission_id"] and not parent["is_video"]:
                target = parent["submission_id"]
    if not target:
        return None
    try:
        u = await get_submission_image_url(target)
        return await download_bytes(u) if u else None
    except Exception:
        logger.exception("wall: reply-chain photo re-fetch failed")
        return None


@app.get("/api/chats")
async def chats_overview(user=Depends(require_user)):
    """The chat-list home in one call: wall preview + unread, teammates with last/unread.
    Does NOT mark anything read — but fetching proves this device RECEIVED pending DMs."""
    try:
        await mark_dm_delivered(user["id"])
    except Exception:
        logger.exception("mark delivered failed")
    wall = await get_wall_overview(user["farm_id"], user["id"])
    peers = await get_dm_peers(user["farm_id"], user["id"])
    return {
        "wall": (None if not wall else {
            "author": ("Flagleaf" if wall["is_bot"] else wall["author"]),
            "body": wall["body"] or ("🎥 видео" if wall["is_video"] else "📷 фото" if wall["has_media"] else ""),
            "created_at": wall["created_at"].isoformat() if wall["created_at"] else None,
            "unread": wall["unread"],
        }),
        "peers": [
            {"id": r["id"], "name": r["name"], "role": r["role"],
             "last_body": r["last_body"], "last_at": r["last_at"].isoformat() if r["last_at"] else None,
             "last_mine": r["last_sender"] == user["id"] if r["last_sender"] is not None else False,
             "unread": r["unread"]}
            for r in peers],
    }


@app.get("/api/wall")
async def wall_get(user=Depends(require_user)):
    rows = await get_wall(user["farm_id"], user["id"], 80)
    if rows:
        try:
            await mark_wall_seen(user["id"], max(r["id"] for r in rows))
        except Exception:
            logger.exception("mark wall seen failed")
    msgs = [{
        "id": r["id"], "body": r["body"], "is_bot": r["is_bot"], "author_id": r["author_id"],
        "author": ("Flagleaf" if r["is_bot"] else r["author"]),
        "chief": (not r["is_bot"]) and r["author_role"] in ("chief_agronomist", "admin"),
        "media": _presign(r["image_url"]), "is_video": bool(r["is_video"]), "field": r["field_name"],
        "reply_to": r["reply_to"],
        "reply_author": (("Flagleaf" if r["reply_is_bot"] else r["reply_author"]) if r["reply_to"] else None),
        "reply_snippet": ((r["reply_body"] or ("📷 фото" if r["reply_has_media"] else "")) if r["reply_to"] else None),
        "ups": r["ups"], "downs": r["downs"], "my_reaction": r["my_reaction"],
        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
    } for r in rows]
    return {"messages": msgs, "me": {"id": user["id"], "role": user["role"], "name": user["full_name"]}}


@app.post("/api/wall")
async def wall_post(request: Request, user=Depends(require_user),
                    body: str = Form(""), field_id: str = Form(""), crop: str = Form(""),
                    reply_to: str = Form(""), image: UploadFile | None = File(None),
                    video: UploadFile | None = File(None)):
    """Post one message to the flat team wall. Media is stored (+ auto Flagleaf reply); text gets
    a reply only when it @flagleafs. A reply_to quotes another message (and, if that message is a
    photo, an @flagleaf re-looks at it)."""
    if not await _rate_ok(_client_ip(request), "feed", FEED_PER_HOUR):
        raise HTTPException(429, "Слишком много сообщений. Попробуйте позже.")
    txt = body.strip()
    fid = int(field_id) if field_id.strip().isdigit() else None
    cr = crop.strip() or None
    rid = int(reply_to) if reply_to.strip().isdigit() else None
    reply_msg = await get_wall_message(rid) if rid else None
    if rid and (not reply_msg or reply_msg["farm_id"] != user["farm_id"]):
        rid, reply_msg = None, None

    sub_id, ctx, has_media = None, None, False
    if image is not None:
        img = await image.read()
        if not img:
            raise HTTPException(400, "Фото не загрузилось. Попробуйте ещё раз.")
        if len(img) > MAX_IMG:
            raise HTTPException(413, "Фото слишком большое (макс. 12 МБ).")
        sub_id = await _store_photo_submission(user, img, image.content_type or "image/jpeg", field_id, txt)
        if sub_id is None:
            raise HTTPException(502, "Не удалось сохранить фото. Попробуйте ещё раз.")
        ctx = flagleaf.Context(image=img, text=txt or None, crop=cr); has_media = True
    elif video is not None:
        data = await video.read()
        if not data:
            raise HTTPException(400, "Видео не загрузилось. Попробуйте ещё раз.")
        if len(data) > MAX_VIDEO_COMMENT:
            raise HTTPException(413, "Видео слишком большое (макс. 60 МБ). Снимите короче.")
        try:
            sub_id = await _store_scout_video(user, data, video.content_type or "video/mp4", field_id, txt)
        except Exception:
            logger.exception("wall: video store failed")
        ctx = flagleaf.Context(video=data, text=txt or None, crop=cr); has_media = True
    if not (sub_id or ctx or txt):
        raise HTTPException(400, "Пустое сообщение.")

    row = await create_wall_message(user["farm_id"], user["id"], False, txt or None, sub_id, fid, rid)
    msg_id = row["id"]

    # notify @-mentioned teammates + whoever you replied to
    mem = await get_farm_members(user["farm_id"])
    targets = _mention_targets(txt, mem, user["id"])
    if reply_msg and reply_msg["author_id"] and reply_msg["author_id"] != user["id"]:
        targets.add(reply_msg["author_id"])
    if targets:
        _push_bg(list(targets), user["full_name"] or "Новое сообщение", txt or "📷 фото")

    # Flagleaf replies: automatically to media, when @flagleaf'd, or when you REPLY to (quote) one
    # of its messages — quoting the bot continues the conversation. Generated in the BACKGROUND so
    # the POST returns instantly (recognition is 20-40s); the reply lands via the client's poll.
    replying_to_bot = bool(reply_msg and reply_msg["is_bot"])
    triggered = has_media or flagleaf.mentions_bot(txt) or replying_to_bot
    if triggered:
        if ctx is None:                                # text trigger (@flagleaf or quoting the bot)
            ctx = flagleaf.Context(
                image=await _reply_photo_bytes(reply_msg), text=flagleaf.strip_address(txt),
                crop=(reply_msg["crop"] if reply_msg else cr),
                field_hint=(reply_msg["field_name"] if reply_msg else None),
                history=_wall_history(await recent_wall(user["farm_id"])))
        _t = asyncio.create_task(_wall_bot_reply(user["farm_id"], user["id"], msg_id, ctx))
        _wall_tasks.add(_t)
    elif txt and settings.flagleaf_proactive in ("shadow", "live"):
        _t = asyncio.create_task(_wall_shadow(user["farm_id"], msg_id, txt))
        _wall_tasks.add(_t)
    return {"ok": True, "id": msg_id}


async def _wall_shadow(farm_id, msg_id, txt):
    """SHADOW MODE: judge whether Flagleaf would usefully chime in unsummoned, and LOG the
    would-be line. Posts nothing (until we've read the log and decided it's worth it)."""
    try:
        res = await flagleaf.evaluate_proactive(txt, _wall_history(await recent_wall(farm_id)))
        if res:
            await log_shadow(farm_id, msg_id, txt, res["confidence"], res["line"])
    except Exception:
        logger.exception("wall shadow eval failed")
    finally:
        _wall_tasks.discard(asyncio.current_task())


_wall_tasks: set = set()   # keep strong refs so background replies aren't GC'd mid-flight


async def _wall_bot_reply(farm_id, asker_id, reply_to_id, ctx):
    try:
        reply = await flagleaf.respond(ctx)
        if reply:
            await create_wall_message(farm_id, None, True, reply, None, None, reply_to_id)
            await _push_notify([asker_id], "Flagleaf", reply)
    except Exception:
        logger.exception("wall bot reply failed")
    finally:
        _wall_tasks.discard(asyncio.current_task())


@app.get("/api/shadow")
async def shadow_log(user=Depends(require_user)):
    """Admin/chief view of Flagleaf's proactive SHADOW log — what it WOULD have said unsummoned,
    plus a 7-day hit-rate denominator. For deciding whether to let the bot self-initiate."""
    if user["role"] not in ("admin", "chief_agronomist"):
        raise HTTPException(403, "Только для руководителя.")
    rows = await get_shadow(user["farm_id"], 100)
    st = await shadow_stats(user["farm_id"], 7)
    return {
        "mode": settings.flagleaf_proactive,
        "stats_7d": {"human_texts": st["human_texts"], "flagged": st["flagged"]},
        "candidates": [{
            "message_id": r["message_id"], "trigger": r["trigger_text"],
            "confidence": round(r["confidence"] or 0, 2), "line": r["line"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        } for r in rows],
    }


@app.post("/api/wall/{message_id}/react")
async def wall_react(message_id: int, body: FeedReact, user=Depends(require_user)):
    """Chief 👍/👎 on a message — the ground-truth signal that drives the labeling gate on the
    message's photo (👍 → into training, 👎 → out)."""
    _require_chief(user)
    v = body.verdict if body.verdict in ("up", "down", "none") else "none"
    await set_wall_reaction(message_id, user["id"], v)
    if v in ("up", "down"):
        msg = await get_wall_message(message_id)
        if msg and msg["author_id"] and msg["author_id"] != user["id"]:
            _push_bg([msg["author_id"]], "Вердикт старшего",
                     ("✅ подтвердил: " if v == "up" else "❌ отклонил: ") + (msg["body"] or "фото"))
        if msg and msg["submission_id"]:
            try:
                sub = await get_submission_review(msg["submission_id"])
                if sub:
                    if v == "down" and sub["status"] != "rejected":
                        await update_submission(msg["submission_id"], status="rejected")
                    elif v == "up" and sub["status"] in ("pending_review", "rejected"):
                        await update_submission(msg["submission_id"], status=approved_status(sub))
            except Exception:
                logger.exception("wall react: submission status update failed")
    return {"ok": True}


@app.get("/api/chat/history")
async def chat_history(user=Depends(require_user)):
    """The signed-in user's «Личное» thread with Flagleaf — server-side, so it survives
    app restarts and follows the account across devices."""
    rows = await get_bot_chat(user["id"])
    return {"messages": [{"role": r["role"], "text": r["body"],
                          "created_at": r["created_at"].isoformat()} for r in rows]}


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
    plan, field_ctx = await _field_route(q)           # field questions answered in-chat (no commands on web)
    ans = plan or await agro_answer(full_q, context=field_ctx, history=_format_history(body.history)) \
        or "Не понял вопрос — переформулируйте, пожалуйста."
    user = await _optional_user(request)
    if user:                                          # signed-in turns persist (restart/device-proof)
        try:
            await save_bot_chat(user["id"], "user", q)
            await save_bot_chat(user["id"], "bot", ans)
        except Exception:
            logger.exception("bot chat save failed")
    return {"answer": ans}


@app.post("/api/chat/stream")
async def chat_stream(body: ChatIn, request: Request):
    """Same as /api/chat but streams the answer token-by-token (StreamingResponse of plain
    UTF-8 text deltas). Grounding runs first (awaited), then the completion streams — so the
    reply starts appearing in ~1 s instead of after the whole thing is written."""
    q = (body.question or "").strip()
    if not q:
        raise HTTPException(400, "empty question")
    if len(q) > MAX_Q:
        raise HTTPException(413, "question too long")
    if not await _rate_ok(_client_ip(request), "chat", CHAT_PER_HOUR):
        raise HTTPException(429, "Слишком много запросов. Попробуйте позже.")
    crop = (body.crop or "").strip()
    full_q = f"Культура: {crop}. {q}" if crop else q
    field_ctx = None
    if not body.structured:                          # assistant only — the scan sets structured=True
        plan, field_ctx = await _field_route(q)
        if plan:                                     # «план по полю 39» → return the generated plan
            return StreamingResponse((c for c in [plan]), media_type="text/plain; charset=utf-8",
                                     headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"})
    assembled = await assemble_prompt(full_q, context=field_ctx,
                                      history=_format_history(body.history), structured=body.structured)
    if not assembled:
        raise HTTPException(503, "Ассистент временно недоступен.")
    sys_text, user_text, max_toks = assembled

    def gen():
        try:
            got = False
            for delta in stream_complete(sys_text, user_text, max_toks):
                got = True
                yield delta
            if not got:
                yield "Не понял вопрос — переформулируйте, пожалуйста."
        except Exception:
            logger.exception("chat stream failed")
            yield "\n⚠️ Не удалось получить ответ. Попробуйте ещё раз."

    # X-Accel-Buffering: no → nginx forwards chunks immediately instead of buffering.
    return StreamingResponse(gen(), media_type="text/plain; charset=utf-8",
                             headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"})


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


MAX_VIDEO_COMMENT = 60 * 1024 * 1024      # ~60 MB — a short clip; long videos are slow on mobile


@app.post("/api/diagnose-video")
async def diagnose_video_ep(request: Request, video: UploadFile,
                            question: str = Form(""), crop: str = Form(""),
                            field_id: str = Form("")):
    """Comment on a short field video AND file it as a scouting record for learning (one upload
    does both). Pulls the sharpest frames (ffmpeg) + transcribes narration → the in-RU vision
    model reasons across the frames (it reads stills, not motion). When signed in, the clip is
    also stored as a scouting field-state record (→ chief review / plan)."""
    data = await video.read()
    if not data:
        raise HTTPException(400, "empty video")
    if len(data) > MAX_VIDEO_COMMENT:
        raise HTTPException(413, "Видео слишком большое — снимите короче (5–15 сек).")
    if not await _rate_ok(_client_ip(request), "diag", DIAG_PER_HOUR):
        raise HTTPException(429, "Слишком много запросов. Попробуйте позже.")
    # Store-for-learning first (best-effort) so the observation is captured even if vision fails.
    user = await _optional_user(request)
    if user:
        try:
            await _store_scout_video(user, data, video.content_type or "video/mp4",
                                     field_id, question)
        except Exception:
            logger.exception("diagnose-video: store-for-learning failed")
    frames = await asyncio.to_thread(extract_frames, data)
    if not frames:
        return {"answer": "Записал видео. Определить по кадрам не удалось — пришлите короткий "
                          "ролик почётче (5–15 сек) или фото крупным планом."}
    narration = ""
    try:
        narration = await asyncio.to_thread(transcribe_video, data)
    except Exception:
        logger.exception("diagnose-video: transcription failed")
    ans = await diagnose_video_frames(frames, question.strip() or None,
                                      crop.strip() or None, None, narration or None)
    return {"answer": ans or (
        "Записал видео. Разобрать автоматически не удалось — опишите проблему словами "
        "или пришлите чёткое фото крупным планом.")}


@app.post("/api/recognize")
async def recognize(request: Request, image: UploadFile, crop: str = Form("")):
    """Structured weed recognition for the scan journey — the guess card (top + alternatives +
    confidence). Wraps the in-RU qwen vision call diagnose already runs internally; the decision
    (product/dose/timing/savings) is a separate /api/chat/stream call once the user picks."""
    img = await image.read()
    if not img:
        raise HTTPException(400, "empty image")
    if len(img) > MAX_IMG:
        raise HTTPException(413, "image too large")
    if not await _rate_ok(_client_ip(request), "diag", DIAG_PER_HOUR):
        raise HTTPException(429, "Слишком много фото-запросов. Попробуйте позже.")
    vd = await asyncio.to_thread(_vision_recognize, img)
    if not vd:
        return {"ok": False}
    return {
        "ok": True,
        "top": {"latin": vd.get("latin"), "ru": vd.get("diagnosis"),
                "confidence": vd.get("confidence"), "class": vd.get("weed_class"),
                "category": vd.get("category"), "phase": vd.get("phase")},
        "alternatives": vd.get("differential") or [],
    }


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
