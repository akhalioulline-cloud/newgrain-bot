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

## 2. OPTIONAL — also carry the verbatim thread

**On the machine you're LEAVING** (send this session's transcript to the other Mac):
```bash
# leaving mac-mini → send to the Air:
tailscale file cp "$(ls -t ~/.claude/projects/*newgrain*/*.jsonl | head -1)" alexeys-macbook-air:
# leaving the Air → send to mac-mini:
tailscale file cp "$(ls -t ~/.claude/projects/*newgrain*/*.jsonl | head -1)" mac-mini:
```

**On the machine you're ARRIVING at:**
```bash
tailscale file get ~/Downloads/                       # 1. pull the Taildrop'd file
cd ~/newgrain-bot && claude                           # 2. (first time only) open once, then /exit — creates the project folder
mv ~/Downloads/*.jsonl "$(ls -dt ~/.claude/projects/*newgrain* | head -1)/"   # 3. file it
cd ~/newgrain-bot && claude --resume                  # 4. pick the session → full scrollback, continue it
```

---

## Gotchas we already hit (so they don't bite again)
- **`no such file: ./scripts/pickup.sh`** → stale clone. The `git pull origin main` first (step 1) fixes it.
- **`command not found: claude`** → the CLI isn't installed on that machine. Run step 0.1. (The Claude GUI app ≠ the `claude` CLI.)
- **Taildrop file "not showing"** → it doesn't pop up automatically. Pull it: `tailscale file get ~/Downloads/` (Tailscale must be Connected).

## The one rule
**One active machine at a time.** Always `handoff` before leaving, `pickup` before starting. If `pickup` reports a git conflict, you edited both machines — tell Claude and it'll merge.
