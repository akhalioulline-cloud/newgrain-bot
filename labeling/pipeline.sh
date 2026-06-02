#!/usr/bin/env bash
# Nightly Stage-2 labeling pipeline: push new photos to CVAT, pull completed batches back.
# Installed on the prod VM at /home/newgrain/newgrain-bot/labeling/pipeline.sh, run by cron 03:30.
# Mirrors backup.sh: uses throwaway one-off containers (`run --rm`) so the live bot is untouched.
# NOTE: no `set -e` — export exits 1 when nothing is pending, which is normal, not a failure.
cd "$(dirname "$0")/.."   # repo root (this script lives in labeling/)
COMPOSE="docker compose -f docker-compose.prod.yml"
echo "===================== labeling pipeline $(date '+%F %T %Z') ====================="

# 1. EXPORT — ready_for_labeling submissions → a CVAT batch task (batch-YYYYMMDD).
#    rc 0 = a batch was created · rc 1 = nothing pending (fine) · rc 2 = upload error.
echo "--- export ---"
$COMPOSE run --rm bot python -m labeling.export
rc=$?
case $rc in
  0) echo "export: batch created." ;;
  1) echo "export: nothing pending — skipped." ;;
  *) echo "export: ERROR (rc=$rc)." ;;
esac

# 2. IMPORT — pull back every CVAT task the annotator marked 'completed'.
echo "--- import (auto) ---"
$COMPOSE run --rm bot python -m labeling.import --auto
echo "import: rc=$?"

echo "===================== done $(date '+%F %T %Z') ====================="
