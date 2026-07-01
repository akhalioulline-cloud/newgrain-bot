"""Chief-agronomist verification card for scouting videos (Pilot v2).

Almas asked that agronomists' scouting videos pass his verification before being
"finally pulled" — just as diagnostic photos already do. Juniors' videos land at
status='pending_review'; once the collector has transcribed the narration it calls
`send_video_review_for`, which pushes a card (transcript + a watch link + Confirm/
Reject buttons) to the farm's chief agronomist. The button taps are handled by
`on_review` in handlers.py (shared with the photo review), which flips a confirmed
scouting video to 'stored' (feeds /plan) or a rejected one to 'rejected'.

Kept in its own module so the video collector (a lean cron script) can import the
sender without pulling in the whole aiogram handler graph.
"""
import logging

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.config import settings
from bot.db import get_chief_agronomists, get_submission_review, update_submission
from bot.storage import presigned_get

logger = logging.getLogger(__name__)


def _kb(sid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Поле", callback_data=f"rev:f:{sid}")],
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"rev:ok:{sid}"),
         InlineKeyboardButton(text="🚫 Отклонить", callback_data=f"rev:no:{sid}")],
    ])


def _caption(sub, watch_url: str) -> str:
    lines = [
        "🎥 Видео обследования — на проверку",
        f"👤 Прислал: {sub['submitter'] or '—'}",
        f"📍 Поле: {sub['field_name'] or '—'}",
    ]
    transcript = (sub["comment_voice_text"] or "").strip()
    lines.append(f"🗣 Расшифровка: {transcript[:700]}" if transcript
                 else "🗣 Расшифровка: (без голосового комментария)")
    lines.append(f"\n▶️ Смотреть видео: {watch_url}")
    lines.append("\nПодтвердите — наблюдение попадёт в план. Отклоните — не пойдёт.")
    return "\n".join(lines)


async def send_video_review_for(submission_id: str, video_key: str) -> int:
    """Push the review card for one scouting video to the farm's chief agronomist(s).

    Returns how many chiefs were notified. 0 means nothing to do — either a
    chief/admin uploaded the video (already terminal, not pending_review), or the
    farm has no chief configured, in which case we finalize the video to 'stored'
    so it is never stranded waiting for a reviewer who doesn't exist.
    """
    sub = await get_submission_review(submission_id)
    if not sub or sub["status"] != "pending_review":
        return 0                                   # chief/admin upload or already handled
    chiefs = await get_chief_agronomists(sub.get("farm_id"))
    if not chiefs:
        await update_submission(submission_id, status="stored")   # don't strand it
        logger.info("video %s: no chief agronomist — auto-finalized to stored", submission_id)
        return 0

    watch_url = presigned_get(video_key, expires=7 * 24 * 3600)   # plain video URL, 7-day link
    caption = _caption(sub, watch_url)
    bot = Bot(settings.bot_token)
    sent = 0
    try:
        for c in chiefs:
            try:
                await bot.send_message(c["tg_user_id"], caption, reply_markup=_kb(submission_id),
                                       disable_web_page_preview=True)
                sent += 1
            except Exception:
                logger.exception("send video review card to %s failed", c["tg_user_id"])
    finally:
        await bot.session.close()
    return sent
