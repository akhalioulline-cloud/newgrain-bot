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
- [newgrain-continuity-portability](newgrain-continuity-portability.md) — offsite cold-archive (inert, needs bucket) + dual-market/relocation plan; farms.data_residency
- [newgrain-weedid-llm-bakeoff](newgrain-weedid-llm-bakeoff.md) — vision-LLM weed-ID: in-RU model qwen3.6, Gemini geo-blocked, both mediocre on seedlings/grasses
- [newgrain-roles-review-gate](newgrain-roles-review-gate.md) — bot roles + chief-agronomist (Almas) review gate on juniors' photos
- [newgrain-architecture-audit](newgrain-architecture-audit.md) — Jun 2026 audit: verdict, deferred-by-design vs real debt, ARCHITECTURE.md + tests/CI + CropWise sync flag
- [newgrain-oplog-freetext](newgrain-oplog-freetext.md) — free-text op logging: routing fix, multi-field fan-out, local-fields vs CropWise-catalog gap, КамАЗ open question
- [newgrain-knowledge-corpus](newgrain-knowledge-corpus.md) — competitor «Андрей Тимофеевич» + CyberLeninka CC-BY literature RAG pilot (sources, licensing, limits)
- [feedback-announce-entries](feedback-announce-entries.md) — add an _ANNOUNCEMENTS entry when shipping a user-facing feature (/announce has lagged 3×)
- [newgrain-web-ai](newgrain-web-ai.md) — public web AI demo at ai.flagleaf.ru (FastAPI api service + static chat UI on the bot VM, Phase 1)
- [newgrain-web-email-login](newgrain-web-email-login.md) — web upload login by email (reg.ru SMTP, no Telegram/VPN); SMTP_PASSWORD in Lockbox
- [newgrain-pwa](newgrain-pwa.md) — installable Flagleaf PWA (ai.flagleaf.ru/app): one app, two tabs; phases A/B/C/D done
- [newgrain-motivation-no-gamification](newgrain-motivation-no-gamification.md) — no points/leaderboards; loop-closing recognition + team goal instead (why + what's built)
- [newgrain-pilot-v2](newgrain-pilot-v2.md) — pivot to field treatment-PLANS + chemical-savings metric; /plan generator, scouting capture, one-pager
- [feedback-auto-handoff](feedback-auto-handoff.md) — run `make handoff` proactively when a unit of work is done; don't wait to be asked
- [newgrain-pyrus-prices](newgrain-pyrus-prices.md) — Pyrus connector (alive) = real historical price/payments source; add bot to payment lists to enumerate → extract → product_prices
- [trading-project](trading-project.md) — SEPARATE parallel project in ~/trading: crypto systematic-trading learning sandbox (OKX, $1000 educational, no MOEX); backtest/robustness/paper-trade toolkit
- [newgrain-app-v2-vision](newgrain-app-v2-vision.md) — App v2 strategy: perception-data company, re-pointed journey, native/offline, model/data, robotics thesis, team-social (full plan docs/app-v2-plan.md)
- [newgrain-flagleaf-ear-native](newgrain-flagleaf-ear-native.md) — Flagleaf/Ear separation + go-native-via-Expo decision & rationale
