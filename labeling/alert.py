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


def send(msg: str) -> int:
    """Send `msg` to every ADMIN_TG_IDS chat. Returns count delivered.
    Best-effort and exception-safe — callers can ignore failures."""
    msg = (msg or "(no message)").strip()
    if not settings.bot_token or not settings.admin_ids:
        print("alert: BOT_TOKEN or ADMIN_TG_IDS not set — cannot send.",
              file=sys.stderr)
        return 0
    base = (settings.telegram_api_base or "https://api.telegram.org").rstrip("/")
    sent = 0
    for admin in settings.admin_ids:
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
    return sent


def send_document(filename: str, content: bytes, caption: str = "") -> int:
    """Send an in-memory file (e.g. the annotation reference HTML) to every
    ADMIN_TG_IDS chat as a Telegram document. Returns count delivered."""
    if not settings.bot_token or not settings.admin_ids:
        print("alert: BOT_TOKEN or ADMIN_TG_IDS not set — cannot send.", file=sys.stderr)
        return 0
    base = (settings.telegram_api_base or "https://api.telegram.org").rstrip("/")
    sent = 0
    for admin in settings.admin_ids:
        try:
            r = requests.post(
                f"{base}/bot{settings.bot_token}/sendDocument",
                data={"chat_id": admin, "caption": caption[:1024]},
                files={"document": (filename, content, "text/html")},
                timeout=60,
            )
            if r.status_code == 200:
                sent += 1
            else:
                print(f"alert: doc to {admin} -> HTTP {r.status_code} {r.text[:150]}",
                      file=sys.stderr)
        except Exception as exc:
            print(f"alert: doc to {admin} failed: {exc}", file=sys.stderr)
    return sent


def main() -> int:
    sent = send(" ".join(sys.argv[1:]))
    print(f"alert: delivered to {sent} admin(s).", file=sys.stderr)
    return 0 if sent else 1


if __name__ == "__main__":
    sys.exit(main())
