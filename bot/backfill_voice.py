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
from bot.transcribe import transcribe, translate_en


async def _run() -> int:
    async with engine.connect() as conn:
        rows = (await conn.execute(text(
            "SELECT id, comment_voice_url, comment_voice_text, comment_voice_text_en "
            "FROM submissions "
            "WHERE comment_voice_url IS NOT NULL "
            "AND (comment_voice_text IS NULL OR comment_voice_text = '' "
            "     OR comment_voice_text_en IS NULL OR comment_voice_text_en = '') "
            "ORDER BY created_at"
        ))).mappings().all()

    if not rows:
        print("backfill_voice: nothing to do (all voice notes transcribed + translated).",
              file=sys.stderr)
        return 0

    print(f"backfill_voice: {len(rows)} voice note(s) need RU and/or EN.", file=sys.stderr)
    ru_done = en_done = empty = failed = 0
    for r in rows:
        sid = str(r["id"])
        try:
            key = r["comment_voice_url"].replace(f"s3://{settings.s3_bucket}/", "")
            audio = _client.get_object(Bucket=settings.s3_bucket, Key=key)["Body"].read()

            sets, params = [], {"id": r["id"]}
            if not (r["comment_voice_text"] or "").strip():
                ru = (await transcribe(audio)).strip()
                if ru:
                    sets.append("comment_voice_text = :ru"); params["ru"] = ru; ru_done += 1
            if not (r["comment_voice_text_en"] or "").strip():
                en = (await translate_en(audio)).strip()
                if en:
                    sets.append("comment_voice_text_en = :en"); params["en"] = en; en_done += 1

            if not sets:
                empty += 1
                print(f"  {sid[:8]}: empty result — will retry next run.", file=sys.stderr)
                continue
            async with engine.begin() as conn:
                await conn.execute(text(
                    f"UPDATE submissions SET {', '.join(sets)}, updated_at = NOW() "
                    "WHERE id = :id"
                ), params)
            print(f"  {sid[:8]}: {'+RU ' if 'ru' in params else ''}"
                  f"{'+EN' if 'en' in params else ''}", file=sys.stderr)
        except Exception as exc:
            failed += 1
            print(f"  {sid[:8]}: ERROR {exc}", file=sys.stderr)

    print(f"backfill_voice: {ru_done} transcribed, {en_done} translated, "
          f"{empty} still empty, {failed} failed.", file=sys.stderr)
    if ru_done or en_done:
        try:
            from labeling.alert import send
            send(f"🎤 Flagleaf: голосовые заметки — расшифровано {ru_done}, "
                 f"переведено на EN {en_done}. См. справочник/историю.")
        except Exception:
            pass
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(_run()))
