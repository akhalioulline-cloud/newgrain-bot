"""Re-transcribe voice notes whose inline transcription failed at upload.

When a voice comment arrives, the bot transcribes it inline (bot/transcribe.py)
and stores the text in submissions.comment_voice_text. On the RAM-tight prod
VM this can fail transiently — e.g. the Whisper model isn't loaded yet right
after a container restart, or memory pressure kills it mid-run. The handler
degrades gracefully: it keeps the .ogg in Object Storage and stores no text.

This job finds every submission that has a saved voice file but no transcript
and fills it in from the audio, so transient failures self-heal. Idempotent
and safe to run nightly. A genuinely silent/empty note simply stays untranscribed
and is retried next run (harmless at pilot voice volume).

Run:  python -m bot.backfill_voice
Exit: 0 = all good (or nothing to do) · 2 = one or more transcriptions errored.
"""
import asyncio
import sys

from sqlalchemy import text

from bot.config import settings
from bot.db import engine
from bot.storage import _client
from bot.transcribe import transcribe


async def _run() -> int:
    async with engine.connect() as conn:
        rows = (await conn.execute(text(
            "SELECT id, comment_voice_url FROM submissions "
            "WHERE comment_voice_url IS NOT NULL "
            "AND (comment_voice_text IS NULL OR comment_voice_text = '') "
            "ORDER BY created_at"
        ))).mappings().all()

    if not rows:
        print("backfill_voice: no untranscribed voice notes.", file=sys.stderr)
        return 0

    print(f"backfill_voice: {len(rows)} voice note(s) to transcribe.", file=sys.stderr)
    done = empty = failed = 0
    for r in rows:
        sid = str(r["id"])
        try:
            key = r["comment_voice_url"].replace(f"s3://{settings.s3_bucket}/", "")
            audio = _client.get_object(Bucket=settings.s3_bucket, Key=key)["Body"].read()
            txt = (await transcribe(audio)).strip()
            if not txt:
                empty += 1
                print(f"  {sid[:8]}: empty result — will retry next run.", file=sys.stderr)
                continue
            async with engine.begin() as conn:
                await conn.execute(text(
                    "UPDATE submissions SET comment_voice_text = :t, updated_at = NOW() "
                    "WHERE id = :id"
                ), {"t": txt, "id": r["id"]})
            done += 1
            print(f"  {sid[:8]}: {txt!r}", file=sys.stderr)
        except Exception as exc:
            failed += 1
            print(f"  {sid[:8]}: ERROR {exc}", file=sys.stderr)

    print(f"backfill_voice: {done} transcribed, {empty} still empty, {failed} failed.",
          file=sys.stderr)
    if done:
        try:
            from labeling.alert import send
            send(f"🎤 Flagleaf: дотранскрибировано голосовых заметок за ночь: {done}. "
                 f"Текст добавлен в историю (/history).")
        except Exception:
            pass
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(_run()))
