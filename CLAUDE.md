# NewGrain — project context for Claude

## What this is
A Telegram bot (Г1 / discovery phase) where an agronomist uploads field photos; a backend stores them for an ML labeling/training pipeline. Built per `tech_spec_v3.docx`. Single success metric: agronomist uploads 15–30 photos/week for 12 weeks without reminders. Principle: build to learn, not to scale (spec §3.3 — no analytics, no gamification, single farm, no web cabinet).

## Who I'm working with
The owner is a **non-technical founder** with no coding background, building solo with Claude Code as the implementer. Explain things in plain language, define jargon, and use the pattern: the user makes decisions & sets up accounts; Claude writes the code and gives exact copy-paste commands + how to verify. Flag the blast radius before risky/irreversible steps.

## Spec location
`~/Library/Mobile Documents/com~apple~CloudDocs/SFAI/tech_spec_v3.docx` — reference its section numbers (§1.5 DB schema, §1.4 architecture, §2.x pipeline).

## Stack
aiogram 3 (bot), FastAPI (api, minimal so far), PostgreSQL 16 + PostGIS, Redis (FSM state + future ARQ queue), Yandex Object Storage in prod / MinIO locally (S3), Whisper (voice→text, not built yet). Everything runs via `docker-compose.yml`.

## Repo layout
- `docker-compose.yml` — the whole stack (postgres, redis, minio, api, bot, worker)
- `bot/` — aiogram bot: `main.py` (wiring), `handlers.py` (onboarding + photo FSM), `middlewares.py` (whitelist auth), `db.py` (direct Postgres access), `storage.py` (S3/MinIO), `states.py` (FSM), `config.py` (env settings)
- `api/`, `worker/` — placeholders for now
- `db/migrations/` — Alembic migrations (0001 schema, 0002 weed species seed, 0003 demo farm+fields, 0004 real "New Grain Co" pilot fields — demo fields hidden, not deleted)
- `.env` — secrets (gitignored; must be copied manually between machines)

## How to run
```
docker compose up -d --build
docker compose run --rm api alembic upgrade head   # build/seed the database
docker compose logs -f bot                          # watch bot logs
```
MinIO console: http://localhost:9001 (login = S3_ACCESS_KEY / S3_SECRET_KEY from .env).
DB shell: `docker compose exec postgres psql -U newgrain -d newgrain`.

## Status (as of 2026-05-25)
- ✅ Phase 1 skeleton, Phase 2 DB tables, Phase 4 auth/onboarding, Phase 5 photo flow + FSM (core works end-to-end: photo → field → category → species → comment → saved; photo lands in S3, row in `submissions` with status `ready_for_labeling`).
- Bot runs in **polling mode** (no public webhook/domain needed for dev). FSM state in Redis. Bot talks **directly to Postgres** (the separate API layer is deferred to Phase 8).
- Whitelist bootstrap: Telegram IDs in `ADMIN_TG_IDS` (.env) auto-get access (role `admin`) on /start; everyone else is refused and shown their own ID. Admins add agronomists in-chat with `/adduser <tg_id> <name>` (role `agronomist`, linked to the admin's farm) — no psql needed.

## Not done yet / next options
- Phase 6 ✅ voice transcription. Local **faster-whisper** (`bot/transcribe.py`, model size via `WHISPER_MODEL` env, default `small`) runs in the bot container — no external API. Voice comments are transcribed inline into `submissions.comment_voice_text` and shown back to the user; transcript also appears in `/history`. Model cached in the `whisper_cache` docker volume (downloads ~0.5 GB once). Adding the dep means the bot image must be rebuilt, not just restarted.
- Phase 7 ✅ commands /history, /stats, /fields, /help, /problem (all in `handlers.py`; Telegram command menu set in `main.py`). /problem forwards the report to `ADMIN_TG_IDS` via Telegram (no DB table for reports yet).
- Real pilot fields ✅ (migration 0004): farm "New Grain Co", fields Поле 121/140 (Соя), 171/99 (Подсолнечник), 76/108 (Пшеница). Old demo fields hidden via is_pilot=false (test submissions still reference them).
- Production deploy ✅ Yandex Cloud VM `158.160.46.89` (SSH `newgrain@`, key `~/.ssh/id_ed25519`). Runs `docker-compose.prod.yml` (postgres+redis+bot only, no MinIO/api/worker, no exposed ports, `restart: unless-stopped`). Photos in Yandex Object Storage bucket `newgrain-data-prod` (endpoint `storage.yandexcloud.net`). Server `.env` has real `POSTGRES_PASSWORD` + S3 keys (not in git). Nightly `pg_dump` via `backup.sh` (cron 03:00) → local 7-day rotation + `backups/` in the bucket. Bot runs ONLY in prod now (local dev bot stopped — same token can't have two pollers). Deploy a change: rsync repo to server, then `docker compose -f docker-compose.prod.yml up -d --build`.
- Photo metadata enrichment: EXIF GPS, perceptual-hash dedup, thumbnails.
- Albums (multiple photos in one send) — handled one-at-a-time for now.
