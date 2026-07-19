#!/usr/bin/env bash
# Nightly Stage-2 labeling pipeline: transcribe voice → push photos to CVAT →
# pull completed batches back. Installed on the prod VM at
# /home/newgrain/newgrain-bot/labeling/pipeline.sh, run by cron 03:30.
# Mirrors backup.sh: uses throwaway one-off containers (`run --rm`) so the live
# bot is untouched. Steps run sequentially so the Whisper/CVAT jobs never
# contend for memory on the RAM-tight VM.
# NOTE: no `set -e` — export exits 1 when nothing is pending, which is normal.
cd "$(dirname "$0")/.."   # repo root (this script lives in labeling/)
COMPOSE="docker compose -f docker-compose.prod.yml"
echo "===================== labeling pipeline $(date '+%F %T %Z') ====================="

# 1. VOICE BACKFILL FIRST — fill any missing RU transcript / EN translation
#    from the saved audio, so the reference sheet (built in step 2) shows them.
echo "--- voice backfill ---"
$COMPOSE run --rm -T bot python -m bot.backfill_voice
vrc=$?
echo "voice backfill: rc=$vrc"
if [ "$vrc" -ne 0 ]; then
  $COMPOSE run --rm -T bot python -m labeling.alert \
    "⚠️ Flagleaf: ошибка дотранскрибации/перевода голосовых заметок (rc=$vrc). См. pipeline.log на сервере."
fi

# 2. EXPORT — ready_for_labeling submissions → a CVAT batch task (batch-YYYYMMDD).
#    rc 0 = a batch was created · rc 1 = nothing pending (fine) · rc 2 = upload error.
echo "--- export ---"
$COMPOSE run --rm bot python -m labeling.export
rc=$?
case $rc in
  0) echo "export: batch created."
     # Deliver the annotation reference sheet (thumbnails, Latin name + CVAT
     # code, RU+EN voice, species-in-voice, field/off-pilot) to the annotator.
     echo "--- reference sheet ---"
     $COMPOSE run --rm -T bot python -m labeling.reference --deliver
     echo "reference: rc=$?" ;;
  1) echo "export: nothing pending — skipped."
     # Reference links are presigned for 7 days (hard AWS cap) — while photos still sit
     # un-annotated in CVAT, re-deliver a fresh sheet every Monday so the annotator's
     # link never goes stale. (labeling.reference exits 1 itself when the backlog is
     # empty, so this never spams an idle team.)
     if [ "$(date +%u)" = "1" ]; then
       echo "--- reference refresh (weekly) ---"
       $COMPOSE run --rm -T bot python -m labeling.reference --deliver
       echo "reference refresh: rc=$?"
     fi ;;
  *) echo "export: ERROR (rc=$rc)."
     $COMPOSE run --rm -T bot python -m labeling.alert \
       "⚠️ Flagleaf labeling: ошибка экспорта фото в CVAT (rc=$rc). Вероятно, лимит задач CVAT или связь. См. pipeline.log на сервере." ;;
esac

# 3. IMPORT — pull labels back + recycle task slots.
echo "--- import (auto) ---"
$COMPOSE run --rm bot python -m labeling.import --auto
irc=$?
echo "import: rc=$irc"
if [ "$irc" -ne 0 ]; then
  $COMPOSE run --rm -T bot python -m labeling.alert \
    "⚠️ Flagleaf labeling: ошибка импорта разметки из CVAT (rc=$irc). См. pipeline.log на сервере."
fi

echo "===================== done $(date '+%F %T %Z') ====================="
