# Secrets via Yandex Lockbox — runbook

**Status (2026-06-13):** the deploy-time fetch script is **implemented**
(`deploy/fetch-secrets.sh`, Pattern A — it refreshes only the secret keys in
`.env`, leaving non-secret config untouched). What remains is **three
Yandex-console actions only you can do** (create the secret, grant the service
account, attach it to the VM) — see "Steps to implement". Until those are done,
secrets still live in a gitignored `.env` copied by hand. This replaces
hand-copying with **Yandex Lockbox** as the single source of truth.

## What moves to Lockbox vs stays in plain config

**Move (true secrets):**
- `BOT_TOKEN`
- `POSTGRES_PASSWORD` (and the password embedded in `DATABASE_URL`)
- `S3_ACCESS_KEY`, `S3_SECRET_KEY`
- `CVAT_API_TOKEN`
- `YC_API_KEY`

**Leave in `.env` / `.env.example` (not secret — config):**
- `S3_ENDPOINT`, `S3_BUCKET`, `S3_REGION`, `REDIS_URL`
- `CVAT_HOST`, `CVAT_PROJECT_NAME`
- `YC_FOLDER_ID`, `YC_TRANSLATE_MODEL`
- `TELEGRAM_API_BASE`, `ADMIN_TG_IDS`

## The key idea: the prod VM authenticates *without a key file*
A Yandex Cloud VM can have a **service account attached** to it. The VM then gets
short-lived IAM tokens from the instance metadata — **no secret file to bootstrap**.
Grant that service account `lockbox.payloadViewer` on the secret, and the server
can read Lockbox with zero secrets on disk. This is the elegant part: you stop
storing *any* long-lived secret on the prod box.

For a **laptop/dev machine**, you authenticate the `yc` CLI once (`yc init`, OAuth
browser login) and then pull secrets the same way. So a new machine needs *one*
login instead of a hand-copied `.env`.

## Recommended pattern (A): fetch at deploy time, app unchanged
Keep the app reading `.env` (no code change). A small script regenerates the prod
`.env` from Lockbox right before `docker compose up`:

```bash
# deploy/fetch-secrets.sh  (runs ON the prod VM, which has the SA attached)
set -euo pipefail
SECRET_ID="<lockbox-secret-id>"
yc lockbox payload get --id "$SECRET_ID" --format json \
  | jq -r '.entries[] | "\(.key)=\(.text_value)"' >> .env   # append secrets
# (non-secret config is already in .env from .env.example)
```

Deploy routine becomes: `rsync repo → ssh → ./deploy/fetch-secrets.sh → docker compose -f docker-compose.prod.yml up -d --build`.

(Pattern B — the bot reads Lockbox at startup via `bot/config.py` — is cleaner in
theory but adds an auth dependency to the app boot path; defer it.)

## Steps to implement (≈30–45 min, mostly your YC console clicks)
1. **Create the secret.** YC console → Lockbox → Create secret `flagleaf-prod`,
   add one entry per secret above (key = env name, value = the secret).
2. **Grant the prod VM's service account** `lockbox.payloadViewer` on that secret
   (IAM → the SA → roles, scoped to the secret).
3. **Attach the service account to the VM** if it isn't already (Compute → VM →
   Edit → Service account). Install `yc` + `jq` on the VM (one-time).
4. **Add `deploy/fetch-secrets.sh`** (above) and have `.env` on the server hold
   only the non-secret config; secrets get appended from Lockbox at deploy.
5. **Update the deploy routine** (and `SETUP.md`) to run the fetch before compose.
6. **Dev machines:** `yc init` once (OAuth), then run the same fetch to populate a
   local `.env`. No more hand-copying.
7. **Rotate** by editing the Lockbox entry + re-deploy — no file edits on machines.

## Cost & trade-offs
- **Cost:** Lockbox is a few rubles/month at this scale (per-secret + per-access).
- **Win:** one credential model (attached SA / one `yc` login) instead of copying
  `.env` around; central rotation; access is audited.
- **Caveat:** introduces a dependency on `yc` + Lockbox at deploy. Keep a sealed
  offline copy of the secrets (e.g., in a password manager) as break-glass.
