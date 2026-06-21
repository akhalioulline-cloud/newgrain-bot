---
name: newgrain-architecture-audit
description: "Interim architecture audit (Jun 2026) — verdict, what's deferred-by-design vs real debt, the guardrails added"
metadata: 
  node_type: memory
  type: project
  originSessionId: f6ba0ea2-f3cc-48c0-898d-52d7a10271dd
---

Interim architecture audit done **2026-06-17** (founder worried ad-hoc feature-adding
was wrecking the structure for a future hire). Verdict: **B / B-minus for a Г1
discovery-phase prototype — sound, readable, not a mess.** Each feature went in
consistently (handler + db fn + optional integration module).

**Deferred BY DESIGN — do NOT refactor these prematurely** (matches spec §3.3 "build to
learn, not scale"): no API tier (bot talks to Postgres directly; `api/` is the planned
seam), no ORM (raw parameterised SQL, injection-safe), no job queue (`worker/` stub;
CropWise pushes run inline off the event loop). Revisit at PMF / first engineer hire.

**Real rough edges (fix opportunistically, not now):** `bot/handlers.py` ~1900-line
monolith with flow logic tangled into aiogram handlers; `bot/db.py` ~870-line
god-module (one file = whole data layer); FSM flows only manually tested.

**Guardrails added this session (the cheap, high-value follow-ups the founder approved):**
- **[ARCHITECTURE.md](ARCHITECTURE.md)** — the onboarding map (layers, data model, photo
  lifecycle, CropWise write-safety, "deferred by design" vs "rough edges"). Read-first doc.
- **tests/ + CI** — 28 pure-logic tests (`make test`, GitHub Actions `.github/workflows/ci.yml`,
  green). Cover the bits that have actually had bugs: field matching (the 47→147 regression),
  product/dose/work-type matching, the план-агро-работ guard. `tests/conftest.py` sets a dummy
  DATABASE_URL so bot modules import without a live DB. Tests are PURE-logic only (no FSM/DB/network).
- **CropWise sync flag** (migration 0025): `field_treatments.cropwise_synced_at`. The bot→CropWise
  dual-write isn't transactional; a failed push used to strand the row silently. Now
  `insert_bot_treatment` RETURNs the id, a successful push stamps `synced_at`, unsynced rows are
  recoverable via `db.get_unsynced_bot_treatments` + admin `/unsynced`. (Local re-tap was already
  idempotent via the 0018 natural-key index; this closes the remote-failure gap.) See
  [[newgrain-labeling-pipeline]] for the CropWise push/sync context.

An audit is cheap (~10k LOC Python) — re-run anytime via parallel Explore agents over
layering + maintainability. Related: [[newgrain-status-2026-05]], [[newgrain-prod-deploy]].
