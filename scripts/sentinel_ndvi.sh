#!/usr/bin/env bash
# Weekly fresh per-field NDVI from Sentinel-2 (AWS open mirror), straight to
# vegetation_weekly(source='sentinel'). Scheduled BEFORE ndvi_watch.sh so the
# weekly alert reflects the latest satellite pass. Throwaway one-off container,
# so the live bot is untouched. ~14-day lookback covers 2-3 Sentinel revisits
# (≈5-day cadence) — enough to find a cloud-free scene per field.
cd "$(dirname "$0")/.."   # repo root (this script lives in scripts/)
COMPOSE="docker compose -f docker-compose.prod.yml"
echo "===================== sentinel ndvi $(date '+%F %T %Z') ====================="
$COMPOSE run --rm -T bot python -m catalog.ingest_sentinel_ndvi --days 16
echo "===================== done $(date '+%F %T %Z') ====================="
