#!/usr/bin/env bash
# Weekly CropWise Operations API sync → field_treatments, then active-substance
# enrich. Keeps our copy fresh as agronomists log new operations in CropWise.
# Idempotent: after the first full load it only ADDS new operations (the retire
# step finds no manual rows left to remove). Installed via cron on the prod VM.
set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${PATH:-}
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
C="docker compose -f docker-compose.prod.yml run --rm -T bot"
$C python -m catalog.cropwise_ops_sync
$C python -m catalog.enrich_active_substances
