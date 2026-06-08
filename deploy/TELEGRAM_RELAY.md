# Telegram relay via Cloudflare Worker — setup

**Problem this solves:** Roskomnadzor IP-blocks Telegram's API from Russian
networks (started 2026-06-03). The bot on the RU VM can't reach
api.telegram.org. Cloudflare's edge IS reachable from RU and can't be
blocked wholesale, so we relay Telegram traffic through a Cloudflare Worker.

The bot already supports this: set `TELEGRAM_API_BASE` in the server `.env`
to the Worker URL and it routes all Telegram traffic (commands + photo
downloads) through Cloudflare. Code: `bot/main.py`, `bot/config.py`.

---

## What the founder does (≈15 min, free)

### 1. Create a Cloudflare account
- Go to https://dash.cloudflare.com/sign-up — sign up (free). No domain or
  payment needed; the Worker gets a free `*.workers.dev` URL.

### 2. Create the Worker
- Left sidebar → **Workers & Pages** → **Create application** → **Create
  Worker**.
- Name it `flagleaf-tg` (this becomes part of the URL). → **Deploy** (it
  deploys a hello-world placeholder first).
- Click **Edit code**.
- Delete everything in the editor, then paste the entire contents of
  [`telegram-relay-worker.js`](telegram-relay-worker.js).
- Click **Deploy** (top right).

### 3. (Recommended) Lock it to our bot token
- On the Worker's page → **Settings** → **Variables and Secrets** → **Add**.
- Type **Secret**, name `ALLOWED_TOKEN`, value = the bot token (the long
  `8045...:AAF...` string from `.env`). → **Deploy**.
- This stops anyone else using your Worker as a generic Telegram proxy.

### 4. Copy the Worker URL and send it to Claude
- It looks like `https://flagleaf-tg.<your-subdomain>.workers.dev`.
- Find it on the Worker's page (under the name / "Visit"). Send that URL.

That's it on your side. Claude wires it into the bot and verifies.

---

## What Claude does (after receiving the URL)

1. Quick reachability + relay sanity check from the RU VM:
   `curl https://<worker>.workers.dev/bot<TOKEN>/getMe` should return JSON
   with the bot's info (proves the relay reaches Telegram).
2. Set `TELEGRAM_API_BASE=https://<worker>.workers.dev` in the server `.env`.
3. Recreate the bot container (`up -d bot`).
4. Confirm `Using Telegram API relay: ...` in logs and that updates are
   handled with normal latency.
5. Remove the `extra_hosts` IP-pin stopgap from `docker-compose.prod.yml`
   (no longer needed — the bot no longer connects to api.telegram.org
   directly; it goes through Cloudflare).

---

## If the Worker URL itself is ever throttled

`*.workers.dev` is broadly reachable from RU, but if it degrades, the same
Worker can be served from a custom domain you control on Cloudflare (e.g.
`tg.flagleaf.ru`) — blocking that means blocking your own domain on
Cloudflare, which RKN won't do collaterally. Ask Claude to switch when needed.

## Cost

Cloudflare Workers free tier: 100,000 requests/day. The bot's polling +
photo traffic is far below that. Expected cost: 0 ₽.
