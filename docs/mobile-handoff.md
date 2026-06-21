# Continuing Flagleaf from the iPhone

The iPhone Claude is a **thin peer**: no local repo, no shell, no Docker, no `~/.claude` memory.
So it **can't** run `make pickup`/`make handoff`, restore memory, or test/deploy. It's for
**thinking, drafting, reviewing** — the real work (run/test/deploy) happens on a Mac.

Because `make handoff` now pushes *all* project memory into `docs/claude-context/`, you can brief
the phone from GitHub. Prerequisite: the last Mac ran `make handoff` (now automatic when work wraps up).

Repo: `github.com/akhalioulline-cloud/newgrain-bot`

---

## 1. Pick up on the iPhone — attach the memory from iCloud

The iPhone Claude has **no GitHub connector**, so it can't read the repo. Instead, every
`make handoff` mirrors the memory snapshot to **iCloud Drive → `Flagleaf_context`** (plain
markdown). To pick up:

1. New chat in the Claude app → tap 📎 → **attach `MEMORY.md`** from Files → iCloud Drive →
   `Flagleaf_context` (attach a detail file too, e.g. `newgrain-web-ai.md`, if you need depth).
2. Say:
   > This is the current project memory for Flagleaf (newgrain-bot). Read it and brief me on the
   > open threads and what's in progress before we continue.

(If a GitHub connector ever appears in your Claude app, you can instead point it at
`github.com/akhalioulline-cloud/newgrain-bot` and have it read `docs/claude-context/` directly.)

## 2. Work on the phone
Plan, draft, write code/answers. It **cannot run, test, or deploy** — treat its output as a
*proposal*, not finished work.

## 3. Hand off from the iPhone (bring it back)
The phone can't `git push`. Two ways:
- **GitHub connector with write access:** ask it to commit its changes to a new branch; a Mac
  then `git pull` + merges and runs `make handoff`.
- **Otherwise (default):** ask it to output its files **plus a short "what I did / what's next"
  note**. On a Mac: drop the files in, then `make handoff`. (This is the paste flow used for the
  Phase-2 upload page.)

---

## Want the phone to *truly* run things?
That needs a **cloud / remote Claude Code session** (the repo lives in a cloud sandbox; any device
connects to the same live session). Only then can the iPhone run/test/deploy. With the current
local-repo model, the phone stays draft-only — and that's fine for most on-the-go work.

**Rule of thumb:** Macs = where work happens; iPhone = think/draft/review, briefed from the GitHub
snapshot, output brought back to a Mac.
