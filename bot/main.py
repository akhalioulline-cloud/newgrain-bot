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
    from aiogram.client.session.aiohttp import AiohttpSession
    from aiogram.client.telegram import TelegramAPIServer
    from aiogram.fsm.storage.redis import RedisStorage
    from aiogram.types import BotCommand

    from bot.handlers import router
    from bot.middlewares import AuthMiddleware
    from bot.storage import ensure_bucket

    await ensure_bucket()

    # Route Telegram traffic through a Cloudflare-Worker relay when configured,
    # so the RU VM never connects to api.telegram.org directly (which RKN
    # blocks). The relay mirrors Telegram's URL layout, so from_base() works.
    if settings.telegram_api_base:
        api = TelegramAPIServer.from_base(settings.telegram_api_base.rstrip("/"))
        session = AiohttpSession(api=api)
        logger.info("Using Telegram API relay: %s", settings.telegram_api_base)
        bot = Bot(settings.bot_token, session=session)
    else:
        bot = Bot(settings.bot_token)
    await bot.set_my_commands(
        [
            BotCommand(command="history", description="Последние снимки"),
            BotCommand(command="stats", description="Статистика за неделю"),
            BotCommand(command="fields", description="Ваши пилотные поля"),
            BotCommand(command="finish", description="Закончить незавершённое фото"),
            BotCommand(command="cancel", description="Отменить текущую загрузку"),
            BotCommand(command="problem", description="Сообщить о проблеме"),
            BotCommand(command="help", description="Справка"),
        ]
    )
    dp = Dispatcher(storage=RedisStorage.from_url(settings.redis_url))
    dp.message.middleware(AuthMiddleware())
    dp.callback_query.middleware(AuthMiddleware())
    dp.include_router(router)

    logger.info("Bot starting (polling mode).")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
