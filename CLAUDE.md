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
- `db/migrations/` — Alembic migrations (0001 schema, 0002 weed species seed, 0003 demo farm+fields)
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
- Whitelist bootstrap: Telegram IDs in `ADMIN_TG_IDS` (.env) auto-get access on /start; everyone else is refused and shown their own ID.

## Not done yet / next options
- Phase 6: voice transcription (Whisper) — voice notes are currently saved to S3 but NOT transcribed.
- Phase 7: commands /history, /stats, /fields, /help, /problem.
- Replace demo farm/fields (migration 0003: Поле №3/№7/№12) with the real pilot fields.
- Photo metadata enrichment: EXIF GPS, perceptual-hash dedup, thumbnails.
- Albums (multiple photos in one send) — handled one-at-a-time for now.
- Production deploy to Yandex Cloud; change `POSTGRES_PASSWORD` / `S3_SECRET_KEY` from dev placeholders to real random values.
