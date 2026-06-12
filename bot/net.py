"""Resilience for outbound Telegram calls that go through the Cloudflare relay.

The relay (TELEGRAM_API_BASE) intermittently resets the connection mid-request
(ConnectionResetError / aiohttp ClientOSError). Without a retry, a single dropped
sendMessage aborts the photo flow at whatever step it was on — the agronomist
types a pest name, the follow-up prompt never arrives, and the upload stalls
(recoverable only via /finish). This request middleware retries *transient
transport* failures a few times with a short backoff.

Real Telegram API errors (BadRequest, Forbidden, RetryAfter, …) are NOT caught —
they are not in the transient set, so they propagate unchanged.
"""
import asyncio
import logging

from aiohttp import ClientError
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.exceptions import TelegramNetworkError

logger = logging.getLogger("bot.net")

# Transport-level failures worth retrying. TelegramNetworkError is aiogram's
# wrapper around aiohttp transport errors; we also catch the raw ones in case a
# version surfaces them unwrapped (the relay reset showed up as ClientOSError).
_TRANSIENT = (
    TelegramNetworkError,
    ClientError,
    ConnectionResetError,
    asyncio.TimeoutError,
)


class RelayRetryMiddleware(BaseRequestMiddleware):
    def __init__(self, retries: int = 3, base_delay: float = 0.5) -> None:
        self.retries = retries
        self.base_delay = base_delay

    async def __call__(self, make_request, bot, method):
        last_exc = None
        for attempt in range(1, self.retries + 1):
            try:
                return await make_request(bot, method)
            except _TRANSIENT as exc:
                last_exc = exc
                if attempt == self.retries:
                    break
                delay = self.base_delay * attempt
                logger.warning(
                    "relay request %s failed (%s); retry %d/%d in %.1fs",
                    type(method).__name__, exc.__class__.__name__,
                    attempt, self.retries, delay,
                )
                await asyncio.sleep(delay)
        raise last_exc
