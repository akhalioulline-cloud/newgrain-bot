from aiogram import BaseMiddleware
from aiogram.types import Message

from bot.config import settings
from bot.db import ensure_user, get_active_user


class AuthMiddleware(BaseMiddleware):
    """Whitelist gate. Lets through known active users (and bootstrap admins);
    everyone else gets a polite refusal that shows their Telegram ID."""

    async def __call__(self, handler, event: Message, data):
        tg_id = event.from_user.id
        user = await get_active_user(tg_id)

        if user is None and tg_id in settings.admin_ids:
            user = await ensure_user(tg_id, event.from_user.full_name)

        if user is None:
            await event.answer(
                "Извините, у вас нет доступа к боту NewGrain.\n"
                f"Ваш Telegram ID: {tg_id}\n"
                "Передайте этот номер администратору, чтобы вас добавили."
            )
            return

        data["user"] = user
        return await handler(event, data)
