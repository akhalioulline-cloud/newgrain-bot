"""Self-heal missing voice transcripts and EN translations (voice + typed).

Per submission, fills whatever's missing:
  • voice note → Russian transcript (Yandex SpeechKit) + English (YandexGPT)
  • typed comment → English (YandexGPT)
Inline transcription/translation at upload can fail transiently (network blip,
SpeechKit/YandexGPT hiccup); the handlers degrade gracefully (keep the .ogg and
the Russian text, store no EN). This job backfills from the saved audio/text, so
failures self-heal. Idempotent, safe to run nightly; an empty result is retried
next run. Runs first in pipeline.sh so the reference sheet carries fresh text.

Run:  python -m bot.backfill_voice
Exit: 0 = all good (or nothing to do) · 2 = one or more steps errored.
"""
import asyncio
import sys

from sqlalchemy import text

from bot.config import settings
from bot.db import engine
from bot.storage import _client
from bot.transcribe import transcribe
from bot.translate_llm import translate_ru_to_en


async def _run() -> int:
    async with engine.connect() as conn:
        rows = (await conn.execute(text(
            "SELECT id, comment_voice_url, comment_voice_text, comment_voice_text_en, "
            "       comment_text, comment_text_en "
            "FROM submissions "
            "WHERE (comment_voice_url IS NOT NULL "
            "       AND (comment_voice_text IS NULL OR comment_voice_text = '' "
            "            OR comment_voice_text_en IS NULL OR comment_voice_text_en = '')) "
            "   OR (comment_text IS NOT NULL AND comment_text <> '' "
            "       AND (comment_text_en IS NULL OR comment_text_en = '')) "
            "ORDER BY created_at"
        ))).mappings().all()

    if not rows:
        print("backfill_voice: nothing to do (all notes transcribed + translated).",
              file=sys.stderr)
        return 0

    print(f"backfill_voice: {len(rows)} submission(s) need transcription/translation.",
          file=sys.stderr)
    ru_done = en_done = txt_done = empty = failed = 0
    for r in rows:
        sid = str(r["id"])
        try:
            sets, params = [], {"id": r["id"]}

            # --- voice note: transcribe (SpeechKit) + translate (YandexGPT) ---
            if r["comment_voice_url"]:
                need_ru = not (r["comment_voice_text"] or "").strip()
                need_en = not (r["comment_voice_text_en"] or "").strip()
                if need_ru or need_en:
                    key = r["comment_voice_url"].replace(f"s3://{settings.s3_bucket}/", "")
                    audio = _client.get_object(Bucket=settings.s3_bucket, Key=key)["Body"].read()
                    ru_text = (r["comment_voice_text"] or "").strip()
                    if need_ru:
                        ru_text = (await transcribe(audio)).strip()
                        if ru_text:
                            sets.append("comment_voice_text = :vru"); params["vru"] = ru_text; ru_done += 1
                    if need_en and ru_text:
                        en = (await translate_ru_to_en(ru_text)).strip()
                        if en:
                            sets.append("comment_voice_text_en = :ven"); params["ven"] = en; en_done += 1

            # --- typed comment: translate (YandexGPT) ---
            ctext = (r["comment_text"] or "").strip()
            if ctext and not (r["comment_text_en"] or "").strip():
                ten = (await translate_ru_to_en(ctext)).strip()
                if ten:
                    sets.append("comment_text_en = :ten"); params["ten"] = ten; txt_done += 1

            if not sets:
                empty += 1
                print(f"  {sid[:8]}: empty result — will retry next run.", file=sys.stderr)
                continue
            async with engine.begin() as conn:
                await conn.execute(text(
                    f"UPDATE submissions SET {', '.join(sets)}, updated_at = NOW() "
                    "WHERE id = :id"
                ), params)
            print(f"  {sid[:8]}: {'+voiceRU ' if 'vru' in params else ''}"
                  f"{'+voiceEN ' if 'ven' in params else ''}"
                  f"{'+textEN' if 'ten' in params else ''}", file=sys.stderr)
        except Exception as exc:
            failed += 1
            print(f"  {sid[:8]}: ERROR {exc}", file=sys.stderr)

    print(f"backfill_voice: {ru_done} voice-transcribed, {en_done} voice-translated, "
          f"{txt_done} text-translated, {empty} empty, {failed} failed.", file=sys.stderr)
    if ru_done or en_done or txt_done:
        try:
            from labeling.alert import send
            send(f"🎤 Flagleaf: заметки — расшифровано {ru_done}, переведено голосовых "
                 f"{en_done}, переведено текстовых {txt_done}. См. справочник/историю.")
        except Exception:
            pass
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(_run()))
