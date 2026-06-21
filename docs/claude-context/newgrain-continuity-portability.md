---
name: newgrain-continuity-portability
description: Offsite cold-archive + portability plan for RKN-isolation/relocation and a future dual-market launch
metadata: 
  node_type: memory
  type: project
  originSessionId: 14929a70-b3c4-4758-9cba-8c9e7e0ef10a
---

Continuity/portability foundation built 2026-06-15 (commit f2d5eb8). Serves two futures:
RKN-isolation+farm-relocation abroad, and a later RU+non-RU dual-market launch. Full
plan + recreate-abroad runbook + RU-coupled swap surface: `docs/continuity-and-portability.md`.

**LIVE since 2026-06-15** — AWS S3 bucket `flagleaf-archive-ngc` (us-east-2), IAM user
`flagleaf-mirror`, key scoped list/read/write only (NO delete → append-only archive).
First mirror: 56 objects (41 photos/6 voice/1 reference/8 DB dumps), 0 failures; restore
verified (dump downloaded back, decompressed 6.8→53.1MB, 13 tables, ends with pg_dump
'database dump complete' marker). Config `OFFSITE_S3_*` in server .env (NOT yet Lockbox).
- `catalog/mirror_offsite.py` — incremental photo/voice/reference/backups mirror Yandex OS → offsite.
- `backup.sh` step 3 — also pushes nightly DB dump offsite (env-guarded).
- `scripts/offsite-mirror.sh` — wrapper, LOCAL ONLY (commit was blocked; use direct docker cmd).
- Migration 0021 added `farms.data_residency` (default 'RU') — residency hook for dual-market.
  NOTE: `farms.region` already existed = AGRONOMIC region ('ЦЧР'); do NOT overload it.

**KEY LESSON — Claude is HARD-BLOCKED from bulk data egress to an external bucket** (running
the mirror, scheduling its cron, even committing the wrapper script were all denied as
"exfiltration", uncleared by user auth). So the OWNER runs the first mirror + installs cron
in their OWN terminal; Claude can only do read-side verification (list/download-back). Direct
cmd: `docker compose -f docker-compose.prod.yml run --rm -T bot python -m catalog.mirror_offsite`.

**DONE 2026-06-15:** nightly cron installed (`0 3` backup.sh w/ offsite DB push, `30 3`
mirror_offsite); AWS key rotated to clean-scoped flagleaf-mirror key `…MA7YHXXZ`, old
`…PQK73RZ5` deleted.
**STILL PENDING (minor):** (1) OFFSITE_S3_* only in server .env, NOT Lockbox — a from-scratch
VM rebuild needs them re-added (fold into next secrets work); (2) leftover `_healthcheck.txt`
in bucket (cosmetic, delete via console); (3) OPTIONAL truly-clean key — both old+new secrets
passed through chat, so a leaked transcript = archive read access; founder declined for now.

Key design calls: did NOT refactor voice/storage/LLM into formal adapters (already cleanly
separated — the doc's swap table IS the port plan; churning stable prod code = risk, no gain).
Dual-market legal model = SEGREGATE not REPLICATE: RU customers' personal data stays on RU infra
(152-ФЗ); the cold archive is only for OUR OWN farm's recovery, must not grow into copying other
RU customers' data abroad. See [[newgrain-prod-deploy]].

**Max (МАКС) second front-end — PLANNED 2026-06-17 (docs/max-port-plan.md):** Telegram stays
PRIMARY/reference; Max is an additive MIRROR. One shared backend (db/catalog/agro_chat/
cropwise_*/parse_op/transcribe), two transport adapters — `bot/` (aiogram, Telegram) + future
`bot_max/` (Max Bot API + its aiogram-style Python SDK github.com/max-messenger/max-botapi-python).
Both write the SAME Postgres+CropWise → unified data. Strategic: Max is RU-state-backed → no RKN
throttling / no Cloudflare relay, agronomists already use it, fully in-RU (152-ФЗ-clean). GATING
(founder): register АО «НЗК» as a VERIFIED RU legal entity with Max (self-serve @MasterBot closed
2025) + get a bot token — Max build is BLOCKED until then. Then: pilot /log + Q&A to confirm
parity (buttons/callbacks/photo/voice/location/FSM), port rest if it holds; extract shared logic
from handlers.py incrementally without destabilizing Telegram.
