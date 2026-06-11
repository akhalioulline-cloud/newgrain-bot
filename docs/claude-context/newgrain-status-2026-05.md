---
name: newgrain-status-2026-05
description: NewGrain build status and next-up work as of late May 2026
metadata: 
  node_type: memory
  type: project
  originSessionId: 88a17f24-0305-4186-87de-ccb72cc8bca8
---

As of 2026-05-25: photo flow works end-to-end (photo → field → category → species → comment → saved to S3 + a `submissions` row with status `ready_for_labeling`). Bot runs in **polling mode** (no public webhook needed for dev), FSM state in Redis, bot talks **directly to Postgres** (separate API layer deferred to Phase 8). Whitelist via `ADMIN_TG_IDS` in `.env`.

**Phase 7 done (2026-05-25):** commands /history, /stats, /fields, /help, /problem in `handlers.py`; Telegram command menu set via `set_my_commands` in `main.py`. /problem forwards a free-text report to `ADMIN_TG_IDS` over Telegram (no DB table for reports). New db.py helpers: `get_user_history`, `get_user_stats`.

**Phase 6 done (2026-05-25):** voice transcription via local **faster-whisper** (`bot/transcribe.py`, lazy-loaded model, `WHISPER_MODEL` env default `small`, runs in bot container — no external API; chosen over OpenAI/Yandex for privacy + no Russia network issues). Voice comments transcribed inline → `submissions.comment_voice_text`, shown to user and in `/history`. Model cached in `whisper_cache` docker volume. New dep `faster-whisper` ⇒ bot image must be **rebuilt** (`docker compose build bot`), not just restarted.

**Not done yet:** replace demo farm/fields (migration 0003: Поле №3/№7/№12) with real pilot fields; EXIF GPS + perceptual-hash dedup + thumbnails; albums (multi-photo sends handled one-at-a-time); production deploy to Yandex Cloud (rotate `POSTGRES_PASSWORD` / `S3_SECRET_KEY` off dev placeholders).

Serves [[newgrain-goal-and-principle]].
