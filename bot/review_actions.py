"""Shared chief-agronomist review decisions.

The review gate now lives in two places — the Telegram review buttons (`on_review`
in handlers.py) and the in-app review inbox (`/api/review/*` in api/main.py). Both
route through the helpers here so a photo/video is finalized and the submitter is
notified identically wherever Almas taps Подтвердить / Отклонить.
"""
import logging

from bot.push import send_push

logger = logging.getLogger(__name__)


def approved_status(sub) -> str:
    """Where a submission goes once the chief approves it: a scouting video/pass is
    field-state → terminal 'stored' (feeds /plan, no CVAT); a diagnostic photo goes
    into the labeling queue → 'ready_for_labeling'."""
    return "stored" if (sub and sub.get("category") == "scouting") else "ready_for_labeling"


async def notify_submitter_decision(bot, sub, action: str) -> None:
    """Tell the submitter their photo/video was approved or rejected (Telegram + push).
    `bot` is any aiogram Bot (the polling bot's callback.bot, or the api's relay bot).
    Best-effort — never raises."""
    if not sub or not sub.get("submitter_tg"):
        return
    is_scouting = sub.get("category") == "scouting"
    what = "видео обследования" if is_scouting else "фото"
    tg = sub["submitter_tg"]
    if action == "approve":
        tail = "" if is_scouting else " и отправлено на разметку"
        msg = f"✅ Ваше {what} проверено старшим агрономом{tail}. Спасибо!"
        ptitle = "Видео проверено ✅" if is_scouting else "Фото проверено ✅"
        pbody = f"Старший агроном подтвердил ваше {what}."
    else:
        msg = f"🚫 Ваше {what} отклонено старшим агрономом."
        ptitle = "Отклонено 🚫"
        pbody = f"Старший агроном отклонил ваше {what}."
    try:
        await bot.send_message(tg, msg)
    except Exception:
        logger.exception("notify submitter (%s) failed", action)
    try:
        await send_push(tg, ptitle, pbody)
    except Exception:
        logger.exception("push submitter (%s) failed", action)
