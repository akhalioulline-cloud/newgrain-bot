#!/usr/bin/env bash
# Daily nudge asking each active agronomist to log the day's field operations.
# Cron in the early evening (local end-of-day). Throwaway one-off container.
cd "$(dirname "$0")/.."   # repo root (this script lives in scripts/)
COMPOSE="docker compose -f docker-compose.prod.yml"
echo "===================== op nudge $(date '+%F %T %Z') ====================="
$COMPOSE run --rm -T bot python -m bot.op_nudge
echo "===================== done $(date '+%F %T %Z') ====================="
