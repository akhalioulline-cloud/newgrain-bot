# Switching machines — context + (optional) thread

**Two separate things can travel between your Macs. Decide which you need:**

| | Carries | How | When |
|---|---|---|---|
| **Context** | distilled memory — open threads, decisions, status; a fresh `claude` is fully briefed | git (`handoff`/`pickup`) | **every switch** |
| **Thread** | verbatim scrollback — every message & command of one session | Taildrop the `.jsonl` + `claude --resume` | **optional** — only when you want the exact history |

Devices on the tailnet: **`mac-mini`** and **`alexeys-macbook-air`**.
macOS note: if `tailscale` isn't found, use `/Applications/Tailscale.app/Contents/MacOS/Tailscale`.

---

## 0. One-time setup on EACH machine
1. **CLI:** `curl -fsSL https://claude.ai/install.sh | bash` then `source ~/.zshrc`
   (the `/Applications/Claude.app` GUI is a *different* thing and is not enough)
2. **Repo:** `git clone https://github.com/akhalioulline-cloud/newgrain-bot.git ~/newgrain-bot`
3. **Tailscale:** install + sign in; menu-bar shows **Connected** (needed for Taildrop)

---

## 1. EVERY switch — carry the context (the routine)

**On the machine you're LEAVING:**
```bash
cd ~/newgrain-bot
make handoff                 # saves context + commits + pushes
```

**On the machine you're ARRIVING at:**
```bash
cd ~/newgrain-bot
git pull origin main         # bootstraps the scripts if this clone is stale
./scripts/pickup.sh          # pulls + restores context
claude                       # fresh session, fully briefed
```
Confirm with: *"what are the open threads on Flagleaf?"*

---

## 2. OPTIONAL — also carry the verbatim thread (one command each)

**On the machine you're LEAVING** (after you've exited the Claude session):
```bash
cd ~/newgrain-bot && make thread-out     # auto-detects the other Mac + sends this session's transcript
```

**On the machine you're ARRIVING at:**
```bash
cd ~/newgrain-bot && make thread-in       # pulls the transcript + files it for resume
claude --resume                           # pick the session → full scrollback, continue it
```
`make thread-in` creates the project folder if needed, so `claude --resume` finds the
session even the first time on a machine. (Both need Tailscale **Connected**.)

<details><summary>manual equivalent, if you ever need it</summary>

```bash
# leaving:  tailscale file cp "$(ls -t ~/.claude/projects/*newgrain*/*.jsonl | head -1)" <other-mac>:
# arriving: tailscale file get ~/Downloads/
#           mv ~/Downloads/*.jsonl "$(ls -dt ~/.claude/projects/*newgrain* | head -1)/"
#           claude --resume
```
</details>

---

## Gotchas we already hit (so they don't bite again)
- **`no such file: ./scripts/pickup.sh`** → stale clone. The `git pull origin main` first (step 1) fixes it.
- **`command not found: claude`** → the CLI isn't installed on that machine. Run step 0.1. (The Claude GUI app ≠ the `claude` CLI.)
- **Taildrop file "not showing"** → it doesn't pop up automatically. Pull it: `tailscale file get ~/Downloads/` (Tailscale must be Connected).

## The one rule
**One active machine at a time.** Always `handoff` before leaving, `pickup` before starting. If `pickup` reports a git conflict, you edited both machines — tell Claude and it'll merge.
