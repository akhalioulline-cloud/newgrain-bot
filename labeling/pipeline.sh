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
  0) echo "export: batch created."
     # Deliver the annotation reference sheet (thumbnails + Latin name + CVAT
     # code + voice transcript + field/off-pilot) to the annotator via Telegram.
     echo "--- reference sheet ---"
     $COMPOSE run --rm -T bot python -m labeling.reference --status in_labeling --deliver
     echo "reference: rc=$?" ;;
  1) echo "export: nothing pending — skipped." ;;
  *) echo "export: ERROR (rc=$rc)."
     $COMPOSE run --rm -T bot python -m labeling.alert \
       "⚠️ Flagleaf labeling: ошибка экспорта фото в CVAT (rc=$rc). Вероятно, лимит задач CVAT или связь. См. pipeline.log на сервере." ;;
esac

# 2. IMPORT — pull labels back + recycle task slots.
echo "--- import (auto) ---"
$COMPOSE run --rm bot python -m labeling.import --auto
irc=$?
echo "import: rc=$irc"
if [ "$irc" -ne 0 ]; then
  $COMPOSE run --rm -T bot python -m labeling.alert \
    "⚠️ Flagleaf labeling: ошибка импорта разметки из CVAT (rc=$irc). См. pipeline.log на сервере."
fi

# 3. VOICE BACKFILL — re-transcribe any voice notes whose inline transcription
#    failed at upload (transient on the RAM-tight VM). Runs sequentially after
#    labeling so the two Whisper/CVAT jobs never contend for memory.
echo "--- voice backfill ---"
$COMPOSE run --rm -T bot python -m bot.backfill_voice
vrc=$?
echo "voice backfill: rc=$vrc"
if [ "$vrc" -ne 0 ]; then
  $COMPOSE run --rm -T bot python -m labeling.alert \
    "⚠️ Flagleaf: ошибка дотранскрибации голосовых заметок (rc=$vrc). См. pipeline.log на сервере."
fi

echo "===================== done $(date '+%F %T %Z') ====================="
