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

## 3. Hand off FROM the iPhone (bring it back to a Mac)
The phone can't `git push`, so its work travels back through **iCloud Drive → `Flagleaf_inbox`**:

1. End of the phone session, ask it:
   > Write a short handoff note (what we changed/decided, and the next steps), and output any
   > files you created as separate files.
2. **Save those into `Flagleaf_inbox`** (Files → iCloud Drive → Flagleaf_inbox): use the share/
   "Save to Files" on each generated file, and save the note as e.g. `handoff.md`. For a chat-only
   session, saving just the note is enough.
3. On a **Mac**, tell Claude: *"I worked on the phone — check `Flagleaf_inbox`."* It reads the
   note, integrates the files into the repo, runs `make handoff`, and you delete the inbox files.

If it was pure thinking (no files), even simpler: copy the phone's summary and paste it to Claude
on the Mac — it folds it into memory and hands off.

---

## Want the phone to *truly* run things?
That needs a **cloud / remote Claude Code session** (the repo lives in a cloud sandbox; any device
connects to the same live session). Only then can the iPhone run/test/deploy. With the current
local-repo model, the phone stays draft-only — and that's fine for most on-the-go work.

**Rule of thumb:** Macs = where work happens; iPhone = think/draft/review, briefed from the GitHub
snapshot, output brought back to a Mac.
