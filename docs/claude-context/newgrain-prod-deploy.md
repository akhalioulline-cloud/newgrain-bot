---
name: newgrain-prod-deploy
description: "NewGrain production deployment — Yandex Cloud VM, how to reach it, deploy & backups"
metadata: 
  node_type: memory
  type: project
  originSessionId: 00400038-017e-4a92-be90-dfab003d97b1
---

NewGrain runs in production on a **Yandex Cloud VM** (cloud `newgrain-cloud`, folder `default`).

- **SSH:** `ssh newgrain@158.160.46.89` (key `~/.ssh/id_ed25519` on the founder's Mac; key-only auth). VM = Ubuntu 22.04, 2 vCPU / 4 GB, zone `ru-central1-a`, security group `newgrain-sg` (inbound TCP 22 only; egress all).
- **Stack:** `docker compose -f docker-compose.prod.yml` in `/home/newgrain/newgrain-bot` — only `postgres + redis + bot` (no MinIO/api/worker), no exposed ports, `restart: unless-stopped`. Code baked into image (no bind-mount) → rebuild to ship changes.
- **Storage:** Yandex Object Storage bucket `newgrain-data-prod`, endpoint `https://storage.yandexcloud.net`, region `ru-central1`. Service account `newgrain-bot` (role `storage.editor`) static key. Bucket is private.
- **Secrets:** server `.env` (chmod 600, NOT in git) holds real `POSTGRES_PASSWORD` + S3 keys. Same `BOT_TOKEN` as dev → **only one bot may poll at a time**; the local dev bot was stopped when prod went live.
- **Backups:** `backup.sh` (cron 03:00 daily) → `pg_dump | gzip` to `/home/newgrain/backups` (7-day rotation) + uploaded to `backups/` in the bucket. Log: `/home/newgrain/backups/backup.log`.
- **Deploy a change:** rsync repo from Mac to `newgrain@158.160.46.89:/home/newgrain/newgrain-bot/` (exclude `.git .env __pycache__ .claude`), then **`docker compose -f docker-compose.prod.yml up -d --build bot`** (the `--build` is mandatory — code is baked into the image, NOT bind-mounted; `restart bot` alone keeps running the old image). DB migrations via `docker compose -f docker-compose.prod.yml run --rm bot alembic upgrade head` *after* the rebuild (so the migration script is in the image).

- **Telegram-block incident (started 2026-06-03):** Roskomnadzor began IP-blocking most of Telegram's API ranges from RU networks. Bot couldn't reach api.telegram.org → getUpdates timed out for ~5 days; Almas couldn't upload, no commands worked. General egress (google/yandex) stayed fine; block is **IP-based, not DPI/SNI** (curl --resolve to a non-blocked Telegram IP returns valid HTTP). The founder's out-of-RU VPNs (Hetzner 46.62.138.179, a Google Cloud VPN) are unreachable from the RU VM / disrupted from RU — RKN flags single VPS IPs. **Cloudflare's edge IS reachable from the RU VM** (cloudflare.com → 200) and is impractical to block wholesale → chosen relay path.
  - **Stopgap (live):** `docker-compose.prod.yml` bot service has `extra_hosts: ["api.telegram.org:149.154.167.220"]` pinning a currently-reachable Telegram IP. Fragile — if RKN blocks that IP, rotate to another working Telegram IPv4 (test with `curl --resolve api.telegram.org:443:<ip> https://api.telegram.org/`).
  - **Durable fix (LIVE since 2026-06-08):** Telegram traffic routes through a **Cloudflare Worker** relay. Worker URL `https://flagleaf-tg.akhalioulline.workers.dev` (founder's CF account, free tier; `ALLOWED_TOKEN` secret set = rejects non-our-token paths with 403). Server `.env` has `TELEGRAM_API_BASE=https://flagleaf-tg.akhalioulline.workers.dev`; `bot/main.py` builds Bot with `AiohttpSession(api=TelegramAPIServer.from_base(...))` when that env is set. Worker code = `deploy/telegram-relay-worker.js` (pass-through proxy to api.telegram.org); setup steps = `deploy/TELEGRAM_RELAY.md`. Verified end-to-end from the RU VM: getMe via worker → bot JSON (0.16s, no throttling); 50s of long-polling → 0 errors. **Crucial network fact:** the RU Yandex *datacenter* CAN reach `*.workers.dev` (fast) even though Russian *consumer ISPs* throttle/block Cloudflare — different paths; the bot uses the datacenter path. To deploy/manage the Worker the founder needs dash.cloudflare.com via VPN (one-time); runtime needs no VPN.
  - **extra_hosts IP-pin still present in compose** as a fallback: while `TELEGRAM_API_BASE` is set the bot ignores it (connects to the worker, not api.telegram.org). To revert to the IP-pin path: unset `TELEGRAM_API_BASE` in `.env` + `up -d bot`. Remove the extra_hosts line in a later cleanup once the relay has proven durable over weeks.
  - **Key teaching point:** the user's personal VPN cannot help the bot — the bot reaches Telegram from the RU server independently of the user's connection.

Builds on [[newgrain-status-2026-05]].
