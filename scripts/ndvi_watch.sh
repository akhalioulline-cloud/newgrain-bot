#!/usr/bin/env bash
# Weekly proactive NDVI watch. Interprets each pilot field's recent NDVI vs the
# same-crop norm and DMs admins ONLY when a field needs a look (silence = all
# normal). Installed on the prod VM, run by cron (Mondays 06:00). Mirrors
# backup.sh / pipeline.sh: a throwaway one-off container so the live bot is
# untouched.
cd "$(dirname "$0")/.."   # repo root (this script lives in scripts/)
COMPOSE="docker compose -f docker-compose.prod.yml"
echo "===================== ndvi watch $(date '+%F %T %Z') ====================="
$COMPOSE run --rm -T bot python -m bot.ndvi_watch --deliver
echo "===================== done $(date '+%F %T %Z') ====================="
