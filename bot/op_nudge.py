"""Daily nudge — ask each active agronomist to log the day's field operations.

One short message with a button that drops them straight into the in-bot logging
flow (callback oplog:start, handled in handlers.py). Sent by cron in the early
evening. Routes through the Cloudflare relay (TELEGRAM_API_BASE) like alert.py,
so it works from the RU server.
"""
import asyncio
import sys

import requests

from bot.config import settings
from bot.db import get_active_users

_TEXT = "Были сегодня обработки на ваших полях? Запишите — текстом или голосом."
_KB = {"inline_keyboard": [[
    {"text": "➕ Записать обработку", "callback_data": "oplog:start"},
    {"text": "Ничего сегодня", "callback_data": "oplog:none"},
]]}


async def run() -> int:
    users = await get_active_users()
    if not settings.bot_token or not users:
        print("op_nudge: no token or no active users — nothing sent.", file=sys.stderr)
        return 0
    base = (settings.telegram_api_base or "https://api.telegram.org").rstrip("/")
    sent = 0
    for u in users:
        try:
            r = requests.post(
                f"{base}/bot{settings.bot_token}/sendMessage",
                json={"chat_id": u["tg_user_id"], "text": _TEXT, "reply_markup": _KB},
                timeout=20,
            )
            if r.status_code == 200:
                sent += 1
            else:
                print(f"op_nudge: {u['tg_user_id']} -> HTTP {r.status_code}", file=sys.stderr)
        except Exception as exc:
            print(f"op_nudge: {u['tg_user_id']} failed: {exc}", file=sys.stderr)
    print(f"op_nudge: sent to {sent}/{len(users)}.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
