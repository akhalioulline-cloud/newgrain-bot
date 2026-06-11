# SETUP — work on Flagleaf from any machine

This guide lets you stand up the Flagleaf / NewGrain bot project on a **new
machine** and pick up where you left off, then work day-to-day. It also explains
the three portability pieces in this repo:

| Piece | What it's for | Where |
|---|---|---|
| **This guide** | New-machine setup + daily workflow | `SETUP.md` |
| **Context snapshot** | Carries Claude Code's project memory across machines | `docs/claude-context/` + `scripts/claude-memory.sh` |
| **Secrets plan** | Move secrets to Yandex Lockbox (so they're not hand-copied) | `docs/SECRETS_LOCKBOX.md` |

**Mental model:** the **code** lives on GitHub (clone it anywhere). The **secrets**
(`.env`) and the **prod SSH key** are the only things you carry by hand for now.
The **context** (what Claude already knows about the project) travels via the
snapshot in this repo. Production already runs in Yandex Cloud — you don't move it.

---

## A. First-time setup on a new machine

### Prerequisites
- **git**, **Docker Desktop** (or Docker Engine), and a terminal.
- **Claude Code** — install: `curl -fsSL https://claude.ai/install.sh | bash`
- Your usual way of reaching Anthropic (see the ⚠️ note at the bottom — from Russia
  Claude Code needs your VPN/access method; that's true on every machine).

### Step 1 — clone the code
```bash
git clone https://github.com/akhalioulline-cloud/newgrain-bot.git
cd newgrain-bot
```
✅ *Verify:* `ls` shows `bot/  labeling/  db/  docker-compose.yml  SETUP.md`.

### Step 2 — secrets (`.env`)
The repo ships `.env.example` (all keys, no values). Copy it and fill in the real
values from your password manager / secure note (or, once set up, from Lockbox —
see `docs/SECRETS_LOCKBOX.md`):
```bash
cp .env.example .env
# then edit .env and paste the real values
```
⚠️ `.env` is gitignored — never commit it. ✅ *Verify:* `grep -c '=' .env` ≈ the
number of keys in `.env.example`, with no empty critical values.

### Step 3 — prod SSH key (only if you deploy/operate prod from this machine)
Copy your prod key into place and lock its permissions:
```bash
# copy the key file you use for the server into ~/.ssh/id_ed25519, then:
chmod 600 ~/.ssh/id_ed25519
```
✅ *Verify:* `ssh newgrain@158.160.46.89 'echo ok'` prints `ok`.

### Step 4 — restore Claude's project context
```bash
./scripts/claude-memory.sh restore
```
This copies the snapshot in `docs/claude-context/` into Claude Code's local memory
folder for this project. ✅ *Verify:* it prints `Restored 8 file(s) -> …/memory`.

### Step 5 — start working
```bash
claude          # from the repo root — CLAUDE.md + the restored memory load automatically
```
For a local test stack (optional — see Section B):
```bash
docker compose up -d --build
docker compose run --rm api alembic upgrade head
```

---

## B. Daily workflow

### Editing code with Claude Code
Run `claude` from the repo root. It auto-loads `CLAUDE.md` (project rules) and the
restored memory. Commit and push as normal — that's how the code travels to your
other machines and to the prod deploy.

### Local test stack (optional)
`docker-compose.yml` runs the full stack locally (postgres, redis, minio, api, bot,
worker) with MinIO standing in for Object Storage.
- ⚠️ **Do not run the bot locally with the *prod* BOT_TOKEN** — Telegram allows only
  one poller per token, so a second one fights the production bot. Use a separate
  dev-bot token in your local `.env` if you want to exercise the bot locally.

### Deploying to production
Production is the Yandex Cloud VM `158.160.46.89` running `docker-compose.prod.yml`.
Code is **baked into the image**, so a rebuild is mandatory (a plain restart keeps
the old code):
```bash
rsync -az --exclude '.git' --exclude '.env' --exclude '__pycache__' ./ newgrain@158.160.46.89:/home/newgrain/newgrain-bot/
ssh newgrain@158.160.46.89 'cd newgrain-bot && docker compose -f docker-compose.prod.yml up -d --build bot'
```
For DB migrations: `ssh … 'cd newgrain-bot && docker compose -f docker-compose.prod.yml run --rm bot alembic upgrade head'`.
- ⚠️ Avoid rebuilding the bot **while the agronomist is actively uploading** — a
  restart can drop an in-flight tap. Coordinate timing.

### Saving context back (so your other machines stay current)
When Claude has learned something worth carrying forward (it lives in machine-local
memory), snapshot it into the repo and commit:
```bash
./scripts/claude-memory.sh save
git add docs/claude-context && git commit -m "update Claude context" && git push
```
Then on another machine: `git pull && ./scripts/claude-memory.sh restore`.

---

## C. How to use the three pieces

**1. This guide (`SETUP.md`)** — follow Section A once per new machine; Section B is
your day-to-day. Keep it updated when the deploy routine or stack changes.

**2. Context snapshot (`docs/claude-context/` + `scripts/claude-memory.sh`)**
- New machine: `./scripts/claude-memory.sh restore` (pulls context in).
- Before committing context updates: `./scripts/claude-memory.sh save` (pushes your
  live memory into the repo), then `git add docs/claude-context && git commit`.
- Personal/unrelated memories (VPN server, the separate marketing-site repo) are
  intentionally **not** synced.
- Note: the script assumes you run `claude` from the repo root (Claude Code keys
  memory by directory path). If your clone path differs, that's fine — the script
  computes the right local folder from the current repo path.

**3. Secrets plan (`docs/SECRETS_LOCKBOX.md`)** — not yet implemented. Read it when
you add a second machine or a teammate; it replaces hand-copying `.env` with a
single Yandex Lockbox source of truth (the prod VM reads it with no secret on disk).

---

## ⚠️ The one thing "the cloud" does NOT solve
Claude Code — CLI, web, or on a VM — must reach **Anthropic's servers**, which is
geo-restricted from Russia. Whatever method you use today (VPN/proxy) is still
required on any machine or cloud box. Hosting doesn't remove that; a stable network
path does. (See the chat discussion on `claude.ai/code` web, Remote Control, and why
a RU cloud dev box can't reach Anthropic.)

## Quick reference
- **Repo:** https://github.com/akhalioulline-cloud/newgrain-bot (private)
- **Prod:** `ssh newgrain@158.160.46.89` · `docker-compose.prod.yml` (postgres + redis + bot)
- **Object Storage:** Yandex, bucket `newgrain-data-prod`
- **Grant docs:** iCloud `Flagleaf/` (Apple devices); move to Drive/Yandex Disk for cross-platform
