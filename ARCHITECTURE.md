# NewGrain — architecture (read this first)

A map of how the bot is put together, for any engineer picking this up. Pair it
with `CLAUDE.md` (project context, status, deploy) and `SETUP.md` (run/secrets).

> **Stage matters.** This is a Г1 *discovery-phase* prototype: one farm, build to
> learn not to scale (spec §3.3). Several things a production system would have —
> a public API layer, an ORM, a service/domain layer, a job queue — are
> **deliberately deferred**, not missing by accident. See "Deferred by design" below
> so you don't mistake a conscious choice for tech debt.

---

## 1. The big picture

```
        Telegram (agronomist)                      Yandex Cloud VM
                │                                ┌──────────────────────┐
        photo / voice / text                     │  bot  (aiogram poll) │
                │                                 │   │                  │
                ▼                                 │   ├── Postgres+PostGIS (data)
   ┌────────────────────────┐   polling          │   ├── Redis (FSM state)
   │  Cloudflare relay       │◀────────────────────   ├── Object Storage (photos/voice)
   │  (TELEGRAM_API_BASE)    │  (RKN workaround)  │   └── external calls:
   └────────────────────────┘                    │        • YandexGPT  (parse / translate / Q&A)
                                                  │        • qwen vision (weed suggest)
                                                  │        • faster-whisper (voice→text, in-process)
                                                  │        • CropWise Operations API (field ops)
                                                  └──────────────────────┘
```

There is **no web server in the request path**. The bot runs in **long-polling**
mode (`bot/main.py` → aiogram `Dispatcher.start_polling`). It talks **directly** to
Postgres, Redis, S3 and the external APIs. That directness is the single most
important thing to understand about the codebase: there is no API tier or service
layer between a Telegram handler and the database — by design, for now (§8).

Everything runs under `docker-compose.prod.yml` (postgres + redis + bot only;
no MinIO/api/worker in prod). Local dev uses `docker-compose.yml` (adds MinIO as
the S3 stand-in, plus api/worker stubs).

---

## 2. Layers as they actually exist

| Layer | Where | Notes |
|-------|-------|-------|
| **Presentation / routing** | `bot/handlers.py` (~1900 lines, 56 handlers) | aiogram routers + the FSM step logic. Also holds a lot of flow logic (see §7). |
| **Auth** | `bot/middlewares.py` | One middleware injects a validated `user` dict into every message/callback. Whitelist by `ADMIN_TG_IDS`; admins add agronomists with `/adduser`. |
| **Conversation state** | `bot/states.py` + Redis | aiogram FSM. State *definitions* here; state *transitions* live in handlers. |
| **Domain helpers** | `bot/parse_op.py`, `bot/agro_chat.py`, `bot/weed_suggest.py`, `bot/transcribe.py`, `bot/moa.py`, `bot/fieldmap.py` | Thin, single-purpose modules — mostly wrappers around an external model + the small bit of logic around it. |
| **Data access** | `bot/db.py` (~870 lines, ~37 async fns) | Raw parameterised SQL over an async SQLAlchemy engine. No ORM. One module = the whole data layer. |
| **Object storage** | `bot/storage.py` | boto3 wrapper (`upload_bytes`/`download_bytes`/`delete_object`). Swaps MinIO↔Yandex via env only. |
| **Config** | `bot/config.py` | One pydantic `Settings`. All env vars declared in one place. Prod secrets come from Yandex Lockbox at deploy (`deploy/fetch-secrets.sh`). |
| **External-system integration** | `catalog/cropwise_*.py` | CropWise read-sync + write-push live here (see §5). |
| **Schema / migrations** | `db/migrations/versions/` | Alembic, forward-only, numbered `0001…`. |
| **Data/ML ops scripts** | `catalog/`, `labeling/` | One-off ingest + the CVAT labeling pipeline. Run by hand, not by the bot (except the CropWise modules — §5). |

---

## 3. Data model (the tables that matter)

Defined in `db/migrations/versions/0001_initial_schema.py` and extended by later
migrations. The five tables you'll touch most:

- **`farms`** — the farm (one, for now). PostGIS centroid.
- **`users`** — whitelisted people. `role` ∈ {`admin`, `chief_agronomist`,
  `annotator`, `agronomist`}; `tg_user_id` is the Telegram id; `farm_id` scopes them.
- **`fields`** — a field. `name` is `"Поле <N> · <отделение>"` (or `"Поле <N>"` for
  pilot). PostGIS polygon `geometry` (used for "what field is this GPS point in").
  `is_pilot` hides demo fields without deleting them.
- **`submissions`** — one uploaded **photo** + its labels. The core artefact the
  whole product exists to collect. `status` is the lifecycle (§4). UUID PK.
- **`field_treatments`** — one **agronomic operation** (spray / sowing / tillage…),
  whether bulk-loaded from CropWise or logged in the bot (`source` column). The
  natural-key unique index (`uq_treat_natkey`, migration 0018) makes ingest
  idempotent — the same operation can never double-count across sources.

Reference/derived tables: `weed_species` (dictionary), `treatments` (legacy/seed),
`pesticide_applications` (the Госкаталог registry, ~14k rows, grounds Q&A advice),
plus weather/NDVI tables loaded by `catalog/ingest_*`.

---

## 4. The submission (photo) lifecycle

A photo's `submissions.status` moves through:

```
draft → awaiting_metadata → (pending_review) → ready_for_labeling → labeled → …
```

- **draft / awaiting_metadata** — photo is in S3, labels being collected via the
  `PhotoForm` FSM (field → category → species → comment).
- **pending_review** — only for a junior **agronomist**: the finished photo waits
  for the **chief agronomist** to approve/correct (the review gate). `chief_agronomist`
  and `admin` skip this and go straight to `ready_for_labeling`.
- **ready_for_labeling** — enters the CVAT labeling/training pipeline.

The FSM step→handler mapping lives in `bot/handlers.py`; the states are in
`bot/states.py` (`PhotoForm`, `OpLogForm`, `CAReview`, `CAReport`, `ProblemForm`).

---

## 5. CropWise integration (the one external write path)

CropWise (operations.cropwise.com) is the farm's system of record for field
operations. Two directions:

- **Read sync** — `catalog/cropwise_ops_sync.py` pulls operations into
  `field_treatments` (weekly). Skips our own pushes (idempotency-key prefix).
- **Write push** — when an agronomist logs an operation in the bot (`/log` flow,
  `OpLogForm`), `catalog/cropwise_push.py::push_treatment` creates a completed
  `agro_operation` in CropWise. The report-paste flow
  (`catalog/cropwise_report.py`, operator-only) does the same in bulk from a
  pasted «Задания машин» report, and enforces the field's «план агро работ».

**Write safety (important):** the dual-write (local row + CropWise) is *not* a
distributed transaction. It's made safe by two mechanisms instead:
1. **Local idempotency** — `insert_bot_treatment` is `ON CONFLICT DO NOTHING` on the
   natural key, and we only push to CropWise when a *new* row was inserted. A
   double-tap or re-log can't create a duplicate.
2. **Sync flag** — `field_treatments.cropwise_synced_at` records a successful push.
   A failed push leaves it NULL, so unsynced rows are *findable and re-pushable*
   instead of silently lost (`db.get_unsynced_bot_treatments`; admin `/unsynced`).
   CropWise calls also carry an `idempotency_key`, so a retry won't duplicate remotely.

> ⚠️ `catalog/cropwise_push.py` and `cropwise_report.py` are **both a CLI tool and a
> library imported by the bot**. Running them with `--post` performs **real
> production writes** to CropWise. Use `--dry` to preview. (Tidying this script↔library
> split is on the "when you have an engineer" list, §8.)

---

## 6. Configuration & secrets

- All config is one pydantic `Settings` (`bot/config.py`); read it to see every knob.
- Locally: a gitignored `.env`. In prod: non-secret config in `.env` on the VM;
  **secrets** (DB password, S3 keys, bot token, API keys) live in **Yandex Lockbox**
  (`flagleaf-prod`) and are pulled into `.env` at deploy by `deploy/fetch-secrets.sh`.
- Deploy = `./scripts/deploy.sh` (rsync repo → VM, fetch secrets, rebuild+restart the
  bot container). The bot image **bakes the code**, so a code change needs a rebuild,
  not just a restart. Migrations: `alembic upgrade head` in a one-off `bot` container.

---

## 7. Known rough edges (real, ranked)

These are honest weaknesses, not deferred-by-design choices. Fix opportunistically.

1. **`handlers.py` is a 1900-line monolith.** Flow logic (field resolution, dedup,
   slot-filling) is mixed into aiogram handlers, so it can't be unit-tested without
   the bot running, and another front-end (e.g. Max, §CLAUDE) can't reuse it.
   *Direction:* extract flow logic into plain functions / a `bot/services/` layer;
   handlers become thin.
2. **`db.py` is a 870-line god-module.** Works and is injection-safe, but everything
   is in one file. *Direction:* split into `repositories/` by entity when it next hurts.
3. **Thin automated tests.** `tests/` now covers the pure logic that has actually had
   bugs (field matching, product/dose/work-type matching, the plan guard). The FSM
   flows themselves are still only manually tested.
4. **`api/` and `worker/` are empty stubs** (Phase 8 placeholders) — not wired up.

## 8. Deferred by design (don't "fix" these yet)

Appropriate for the current stage; revisit at product-market fit / first hire:
- **No API tier** — the bot talks to Postgres directly. A FastAPI layer (`api/`) is
  the planned seam for a future web/Max front-end to share logic.
- **No ORM** — raw parameterised SQL is fine at this size and is fully injection-safe.
- **No job queue** — `worker/` is a stub; CropWise pushes run inline off the event
  loop. An ARQ/outbox worker is the scale-up path.
- **Single farm, polling, no webhook/domain** — matches the discovery-phase spec.

---

## 9. Where to start reading

1. `CLAUDE.md` — context, current status, deploy routine.
2. This file — the map.
3. `bot/main.py` — wiring: routers, middleware, command menu, startup.
4. `bot/handlers.py` — follow the `PhotoForm` flow top to bottom once.
5. `bot/db.py` — the data layer; every table touch is here.
6. `tests/` — runnable examples of the trickiest pure logic.
