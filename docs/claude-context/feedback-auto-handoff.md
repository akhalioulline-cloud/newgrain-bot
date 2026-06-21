---
name: feedback-auto-handoff
description: "Proactively run `make handoff` at the end of substantive work — don't wait to be asked"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 8ab3a9ce-165c-4c95-904a-b80b9500a2e9
---

The founder works across machines (Mac, Mac-mini; iPhone for light tasks), one active at a time,
syncing through the GitHub remote (NOT iCloud — an iCloud'd git repo risks corruption; decided
21 Jun 2026). To remove the manual handoff ritual, **proactively run `make handoff` whenever a
meaningful unit of work is wrapped up** — a shipped/deployed feature, a fix verified, the end of a
work session — WITHOUT being asked.

**Why:** founder asked (21 Jun 2026) to make auto-handoff the default, so leaving a machine needs
nothing from them.

**How to apply:** `make handoff` = `scripts/handoff.sh` = `claude-memory.sh save` (snapshot ALL
memory → `docs/claude-context/`) + `git add -A` + commit + push, so the next machine's
`make pickup` (pull + restore) gets full code **and** current context. Glance at `git status`
first so you don't commit junk (.env is gitignored). Don't do it mid-task — only when a unit is
genuinely done. The memory-sync engine it relies on was fixed 21 Jun (auto-discovers all
memories, was a stale 7-file allowlist). See [[workflow-decisions-vs-code]].
