# Claude context snapshot — Flagleaf / NewGrain bot

This folder is a **portable snapshot of Claude Code's project memory** so the
working context travels with the repo to any machine. Claude Code's live memory
lives at `~/.claude/projects/<encoded-path>/memory/` and is **machine-local** —
it does not sync on its own. These files mirror the project-relevant ones.

**On a new machine:** after cloning, run `scripts/claude-memory.sh restore` to
copy these into the local Claude memory dir. **Before committing updates:** run
`scripts/claude-memory.sh save` to refresh this snapshot from your live memory.
(Personal/unrelated memories — VPN server, the separate marketing-site repo —
are intentionally excluded.)

## Index
- [user-nontechnical-founder](user-nontechnical-founder.md) — who the founder is; explain in plain language
- [workflow-decisions-vs-code](workflow-decisions-vs-code.md) — founder decides & sets up accounts, Claude codes + gives copy-paste commands, flag blast radius
- [newgrain-goal-and-principle](newgrain-goal-and-principle.md) — photo-upload Telegram bot; metric = 15–30 photos/wk for 12 wks; build to learn, not scale
- [newgrain-status-2026-05](newgrain-status-2026-05.md) — phase status snapshot
- [newgrain-prod-deploy](newgrain-prod-deploy.md) — Yandex Cloud VM, prod compose, Object Storage, backups, deploy routine
- [newgrain-labeling-pipeline](newgrain-labeling-pipeline.md) — CVAT, schema, export/import/recycle, reference sheet, voice/text RU+EN, pests, dedup
- [newgrain-photo-attribution](newgrain-photo-attribution.md) — Alexey-uploaded submissions are Almas-originated (proxy uploads)
