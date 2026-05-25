import asyncio
import logging

from bot.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bot")


async def main() -> None:
    if not settings.bot_token:
        # No token yet — idle so the container stays up while you finish setup.
        logger.warning("BOT_TOKEN not set. Bot is idling. Add it to .env to go live.")
        while True:
            await asyncio.sleep(3600)

    from aiogram import Bot, Dispatcher
    from aiogram.fsm.storage.redis import RedisStorage

    from bot.handlers import router
    from bot.middlewares import AuthMiddleware
    from bot.storage import ensure_bucket

    await ensure_bucket()

    bot = Bot(settings.bot_token)
    dp = Dispatcher(storage=RedisStorage.from_url(settings.redis_url))
    dp.message.middleware(AuthMiddleware())
    dp.callback_query.middleware(AuthMiddleware())
    dp.include_router(router)

    logger.info("Bot starting (polling mode).")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
