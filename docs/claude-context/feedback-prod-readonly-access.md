---
name: feedback-prod-readonly-access
description: "Founder allows read-only prod queries/log checks directly; writes (deploys, migrations, restarts) stay with the founder"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 3441be93-9176-4fd2-9061-613379401bfe
---

On 5 Jul 2026 the founder explicitly granted: "you are allowed to run read-only queries and
log checks on the prod server yourself" (VM 111.88.248.159, ssh newgrain@, key ~/.ssh/id_ed25519).

**Why:** debugging person-to-person DMs took several rounds of copy-paste ping-pong for simple
SELECTs and `docker compose logs` greps; the founder prefers Claude just runs those.

**How to apply:** psql SELECTs, `to_regclass` checks, `docker compose logs`, `ls` on the VM —
run directly without asking. Anything that CHANGES prod (rsync deploy, alembic upgrade,
container rebuild/restart, cron edits) — still hand the founder copy-paste commands unless
they explicitly ask Claude to deploy. Ties to [[newgrain-prod-deploy]] and
[[workflow-decisions-vs-code]].
