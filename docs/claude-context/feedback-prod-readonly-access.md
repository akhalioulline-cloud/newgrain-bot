---
name: feedback-prod-readonly-access
description: "Founder cleared Claude to run prod ops directly — read-only queries/logs AND the standard deploy (rsync + docker compose build)"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 3441be93-9176-4fd2-9061-613379401bfe
---

On 5 Jul 2026 the founder granted, in two steps: first "you are allowed to run read-only
queries and log checks on the prod server yourself", then "can you deploy yourself without my
copying and pasting" — i.e. Claude may run the full deploy too. VM 111.88.248.159, ssh
newgrain@, key ~/.ssh/id_ed25519.

**Why:** the copy-paste ping-pong (SELECTs, `docker compose logs`, and the multi-line deploy)
was slow and error-prone; the founder prefers Claude just runs them.

**How to apply:**
- Read-only (psql SELECTs, `to_regclass`, `docker compose logs`, `ls`): run directly, no ask.
- **Standard deploy** — `rsync -az --delete … newgrain@…:newgrain-bot/` then
  `docker compose -f docker-compose.prod.yml up -d --build api bot` (add `alembic upgrade head`
  when a migration is pending): run it directly after committing, then verify (curl /api/me →
  401 = healthy; check logs for tracebacks). Auto-mode classifier MAY still block the write
  step — if so, tell the founder. Report deploy results plainly.
- Still pause for genuinely destructive/irreversible ops beyond a normal deploy (DB drops,
  data deletion, secret rotation, infra teardown). Ties to [[newgrain-prod-deploy]] and
  [[workflow-decisions-vs-code]].
