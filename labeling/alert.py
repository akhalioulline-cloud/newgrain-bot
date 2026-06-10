"""Send a short alert to ADMIN_TG_IDS over Telegram.

Used by the nightly labeling cron (`pipeline.sh`) to surface failures
immediately instead of burying them in a log file — the June-2026 CVAT jam
went unnoticed for ~6 days precisely because export errors were silent.

Usage:  python -m labeling.alert "⚠️ текст сообщения"
Routes through TELEGRAM_API_BASE (the Cloudflare relay) when set, so it
works from the RU server despite the Telegram block.
"""
import sys

import requests

from bot.config import settings


def main() -> int:
    msg = " ".join(sys.argv[1:]).strip() or "(no message)"
    if not settings.bot_token:
        print("alert: BOT_TOKEN not set — cannot send.", file=sys.stderr)
        return 1
    base = (settings.telegram_api_base or "https://api.telegram.org").rstrip("/")
    admins = settings.admin_ids
    if not admins:
        print("alert: ADMIN_TG_IDS empty — nobody to notify.", file=sys.stderr)
        return 1

    sent = 0
    for admin in admins:
        try:
            r = requests.post(
                f"{base}/bot{settings.bot_token}/sendMessage",
                json={"chat_id": admin, "text": msg},
                timeout=20,
            )
            if r.status_code == 200:
                sent += 1
            else:
                print(f"alert: chat {admin} -> HTTP {r.status_code}", file=sys.stderr)
        except Exception as exc:
            print(f"alert: chat {admin} failed: {exc}", file=sys.stderr)
    print(f"alert: delivered to {sent}/{len(admins)} admin(s).", file=sys.stderr)
    return 0 if sent else 1


if __name__ == "__main__":
    sys.exit(main())
