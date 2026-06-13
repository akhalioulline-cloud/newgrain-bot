# Productionization roadmap (when NewGrain goes from pilot → product)

**Status:** plan, not to be executed during the Г1 pilot. The current single-VM
setup is the right choice for "build to learn, not to scale" (see CLAUDE.md). This
doc says *what* changes for a marketable product, *when* to start, and in *what
order* — so the move is deliberate, not reactive.

## Where things run today (pilot)
- **Source of truth:** GitHub `akhalioulline-cloud/newgrain-bot`.
- **Edit:** founder's Mac(s) (`~/newgrain-bot`); not where the bot runs.
- **Runs:** one Yandex Cloud VM (`158.160.46.89`), Docker compose — `bot` +
  `postgres` + `redis` in containers, code baked into the image.
- **Data:** Postgres on the VM; photos in Yandex Object Storage; nightly
  `pg_dump` → local 7-day rotation + Object Storage (`backup.sh`, cron 03:00).
- **Secrets:** hand-copied `.env` (gitignored).
- **Deploy:** manual `rsync` repo → VM → `docker compose up -d --build`.

Already product-grade: Object Storage, `farm_id` in the schema (multi-tenant
seed), GitHub, verified backups.

## Don't migrate yet — migrate on a TRIGGER
Move only when one of these is actually true (not before):
1. **A second farm / paying customer** is about to onboard. ← the main one.
2. The pilot **succeeds and you commit to commercializing**.
3. The **single VM or the Telegram relay causes a felt outage** (not hypothetical).
4. A **second developer** joins (manual deploys stop being safe).

Until then, the pilot's real risk is *adoption*, not infrastructure. Migrating
early costs money and slows feature work for zero user value.

## What changes, and in what order
Do these in sequence; each is independently useful. Stop when you've done enough
for your current scale.

| # | Area | Pilot now | Product target | Why / when |
|---|------|-----------|----------------|------------|
| 1 | **Secrets** | hand-copied `.env` | Yandex **Lockbox** (`docs/SECRETS_LOCKBOX.md`, `deploy/fetch-secrets.sh`) | cheap, do when a 2nd machine/teammate appears |
| 2 | **Deploy** | manual rsync + rebuild | **CI/CD**: push → test → build image → registry → deploy | removes manual-deploy mistakes; do with a 2nd dev or before 1st customer |
| 3 | **Database** | Postgres container on the VM | **managed PostgreSQL** (auto backup, failover) | biggest reliability win; do before 1st paying customer |
| 4 | **Redis** | container on the VM | managed Redis | alongside #3 |
| 5 | **Compute** | one 2-core VM | managed containers / K8s (autoscale, self-heal) | when traffic or # farms grows |
| 6 | **Bot transport** | single long-poller + Cloudflare relay | **webhooks** behind a load balancer (multi-instance) | when one instance isn't enough |
| 7 | **Multi-tenancy** | one farm | per-tenant isolation, onboarding, billing, **security review** | before selling to others |
| 8 | **Observability** | logs + a few Telegram alerts | monitoring, error tracking, uptime alerts | with #2/#3 |

**First two worth doing when the trigger hits:** managed PostgreSQL (#3) + CI/CD
(#2) — they remove the two real fragilities (single VM, manual deploys).

## Strategic anchor: stay on Yandex Cloud (Russia)
Farms and data are in RU; the RKN Telegram block already forces a relay, and
Copernicus is blocked from RU while the AWS Sentinel mirror works. An RU-resident,
RU-reachable host (Yandex Cloud) is the right home and keeps data-residency simple.
A US/EU host would fight the network at every step.

## Cost reality
Pilot today: ~one small VM + cheap object storage (low single-digit thousands
₽/mo). A managed product stack (managed PG with failover + managed Redis +
container platform + LB + registry + monitoring) is typically **~5–10× that**, much
of it fixed cost regardless of customer count. So productionize when revenue or a
committed customer justifies it — not to serve one pilot farm.

## Cheap hardening to do *now* (no migration)
- ✅ Backups verified to restore (done 2026-06-13; also fixed a silent 2-week
  backup outage + added failure alerting in `backup.sh`).
- ✅ Roadmap + triggers documented (this file).
- ◻ Move secrets to Lockbox (`docs/SECRETS_LOCKBOX.md`) — small, do when a 2nd
  machine/teammate appears.
- ◻ Keep a sealed offline copy of `.env` (password manager) as break-glass.
