"""Morning review nudge — push + Telegram to each chief agronomist who has material
waiting for verification. Run daily by cron inside the bot container:

    docker compose -f docker-compose.prod.yml exec -T bot python -m bot.morning_review

Single-farm pilot → global pending count. Sends nothing when the queue is empty, so a
chief who cleared everything the day before gets no needless ping. The review itself
happens in the app assistant (link below); this is only the nudge to open it.
"""
import asyncio
import logging
import os

from bot.config import settings
from bot.db import get_chief_agronomists, get_pending_reviews
from bot.push import send_push

logger = logging.getLogger("morning_review")

APP_PATH = "/app/assistant.html?review=1"
WEB_URL = os.getenv("WEB_APP_URL", "https://ai.flagleaf.ru").rstrip("/") + APP_PATH


def _relay_bot():
    """One-off aiogram Bot for the Telegram nudge (mirrors api.main._relay_bot)."""
    from aiogram import Bot
    from aiogram.client.session.aiohttp import AiohttpSession
    from aiogram.client.telegram import TelegramAPIServer
    base = (settings.telegram_api_base or "").rstrip("/")
    if base:
        server = TelegramAPIServer.from_base(base)
        return Bot(settings.bot_token, session=AiohttpSession(api=server))
    return Bot(settings.bot_token)


def _summary(items) -> str:
    ph = sum(1 for it in items if not it["is_video"])
    vd = len(items) - ph
    parts = []
    if ph:
        parts.append(f"{ph} фото")
    if vd:
        parts.append(f"{vd} видео")
    return " и ".join(parts) or f"{len(items)} материалов"


async def main() -> None:
    chiefs = await get_chief_agronomists(None)          # single-farm pilot → all active chiefs
    if not chiefs:
        logger.info("no active chief agronomists — nothing to nudge")
        return
    items = await get_pending_reviews(None)
    if not items:
        logger.info("review queue empty — no morning nudge sent")
        return

    summary = _summary(items)
    title = "🌅 Материалы на проверке"
    body = f"{summary} ждут вашей проверки — откройте «Ассистент»."
    tg_text = (
        f"🌅 Доброе утро! На проверке: {summary}.\n"
        f"Откройте «Ассистент», чтобы разобрать: {WEB_URL}"
    )

    rbot = _relay_bot()
    pushes = 0
    try:
        for c in chiefs:
            tg = c["tg_user_id"]
            if not tg:
                continue
            try:
                pushes += await send_push(tg, title, body, APP_PATH)
            except Exception:
                logger.exception("morning push failed for %s", tg)
            try:
                await rbot.send_message(tg, tg_text, disable_web_page_preview=True)
            except Exception:
                logger.exception("morning telegram failed for %s", tg)
        logger.info("nudged %d chief(s) — %s (%d push deliveries)", len(chiefs), summary, pushes)
    finally:
        await rbot.session.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(main())
