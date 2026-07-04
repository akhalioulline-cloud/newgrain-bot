"""Smart scouting reminder — nudge each agronomist/chief who hasn't scouted in SCOUT_IDLE_DAYS
(push + Telegram). Runs daily by cron inside the bot container:

    docker compose -f docker-compose.prod.yml run --rm -T bot python -m bot.scout_reminder

Only the idle are pinged (no scouting in N days, or never) — so someone who scouted yesterday
gets nothing. The scouting itself happens in the app assistant (link below).
"""
import asyncio
import logging
import os

from bot.config import settings
from bot.db import scouting_idle_users
from bot.push import send_push

logger = logging.getLogger("scout_reminder")

SCOUT_IDLE_DAYS = int(os.getenv("SCOUT_IDLE_DAYS", "3"))
APP_PATH = "/app/assistant.html?scout=1"
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


def _body(days_since) -> str:
    if days_since is None:
        return "Вы ещё не обследовали поля — снимите короткое видео прохода поля или несколько фото."
    return (f"Последнее обследование — {int(days_since)} дн. назад. "
            "Снимите короткое видео прохода поля или несколько фото.")


async def main() -> None:
    idle = await scouting_idle_users(SCOUT_IDLE_DAYS)
    if not idle:
        logger.info("everyone scouted within %d days — no reminder sent", SCOUT_IDLE_DAYS)
        return

    title = "🔭 Пора заскаутить поля"
    rbot = _relay_bot()
    pushes = 0
    try:
        for u in idle:
            tg = u["tg_user_id"]
            if not tg:
                continue
            body = _body(u["days_since"])
            try:
                pushes += await send_push(tg, title, body, APP_PATH)
            except Exception:
                logger.exception("scout push failed for %s", tg)
            try:
                await rbot.send_message(tg, f"{title}\n{body}\nОткройте «Ассистент»: {WEB_URL}",
                                        disable_web_page_preview=True)
            except Exception:
                logger.exception("scout telegram failed for %s", tg)
        logger.info("nudged %d idle scout(s) (%d push deliveries)", len(idle), pushes)
    finally:
        await rbot.session.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(main())
