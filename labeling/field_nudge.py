"""Nudge agronomists back to their demonstration fields when one goes red.

A demonstration field is "red" when it hasn't been observed for >10 days (weekly target +
3-day grace). For each red field we push the agronomist who last scouted it — «вы давно не
были на Поле …». Throttled to once per field per agronomist every 4 days so it's a reminder,
not spam. Run daily from cron.

    docker compose -f docker-compose.prod.yml run --rm -T bot python -m labeling.field_nudge
"""
import asyncio
import sys

import redis.asyncio as aioredis

from bot.config import settings
from bot.db import get_demo_fields_for_nudge
from bot.push import push_enabled, send_push

RED_DAYS = 10
THROTTLE_SEC = 4 * 24 * 3600


async def run() -> int:
    if not push_enabled():
        print("field_nudge: push not configured — skipping.", file=sys.stderr)
        return 0
    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    rows = await get_demo_fields_for_nudge()
    sent = 0
    for f in rows:
        d, tg = f["last_days"], f["last_tg"]
        if d is None or d <= RED_DAYS or not tg:      # not red, or nobody to nudge
            continue
        key = f"flagleaf:fieldnudge:{tg}:{f['id']}"
        try:
            if await r.get(key):                      # already nudged recently
                continue
            n = await send_push(
                tg, "🎯 Контрольное поле",
                f"Вы давно не были на {f['name']} — пора обследовать ({d} дн. назад).", "/app/")
            if n:
                await r.set(key, "1", ex=THROTTLE_SEC)
                sent += 1
        except Exception as exc:  # noqa: BLE001
            print(f"field_nudge: {f['name']} failed: {exc}", file=sys.stderr)
    print(f"field_nudge: sent {sent} reminder(s).", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
