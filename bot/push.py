"""Web Push sender (PWA notifications) via VAPID.

send_push(tg_user_id, …) fans a notification out to all of that user's subscribed
devices. pywebpush is blocking, so each delivery runs in a thread. Dead endpoints
(404/410) are pruned. Disabled (returns silently) if no VAPID private key is set.
"""
import asyncio
import json
import logging

from pywebpush import WebPushException, webpush

from bot.config import settings
from bot.db import delete_push_subscription, get_push_subscriptions

logger = logging.getLogger(__name__)


def push_enabled() -> bool:
    return bool(settings.vapid_private_key and settings.vapid_public_key)


def _webpush_one(sub, payload: str):
    """Returns True on success, None if the subscription is dead (prune it), False on
    a transient error."""
    try:
        webpush(
            subscription_info={
                "endpoint": sub["endpoint"],
                "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]},
            },
            data=payload,
            vapid_private_key=settings.vapid_private_key,
            vapid_claims={"sub": settings.vapid_subject},
            timeout=10,
        )
        return True
    except WebPushException as exc:
        code = getattr(exc.response, "status_code", None)
        if code in (404, 410):
            return None
        logger.warning("webpush failed (%s): %s", code, exc)
        return False
    except Exception as exc:  # noqa: BLE001
        logger.warning("webpush error: %s", exc)
        return False


async def send_push(tg_user_id: int, title: str, body: str, url: str = "/app/") -> int:
    """Push to all of a user's devices. Returns how many were delivered."""
    if not push_enabled() or not tg_user_id:
        return 0
    subs = await get_push_subscriptions(tg_user_id)
    if not subs:
        return 0
    payload = json.dumps({"title": title, "body": body, "url": url})
    sent = 0
    for s in subs:
        res = await asyncio.to_thread(_webpush_one, s, payload)
        if res is None:
            await delete_push_subscription(s["endpoint"])
        elif res:
            sent += 1
    return sent
