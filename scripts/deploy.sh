#!/usr/bin/env bash
# DEPLOY — rsync the repo to the prod VM and rebuild the bot image.
# Code is BAKED into the image, so a plain restart keeps old code — we rebuild.
# ⚠️ Avoid running this while the agronomist is actively uploading: the bot
# restart can drop an in-flight tap.
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# NOTE: ephemeral public IP — it changes if the VM is stopped/started. Reserve a
# static IP to stop this moving. (Tailscale name `flagleaf` is IP-stable but RU
# tailnet SSH is intermittent, so the public IP stays the deploy path.)
SERVER="newgrain@111.88.248.159"

echo "→ rsync repo → prod…"
rsync -az --exclude '.git' --exclude '.env' --exclude '__pycache__' --exclude '*.pyc' \
      --exclude '.claude' --exclude '.DS_Store' ./ "$SERVER:/home/newgrain/newgrain-bot/"

echo "→ refresh secrets from Lockbox + rebuild + restart bot…"
# fetch-secrets is best-effort: if Lockbox/metadata is briefly unreachable, keep
# the existing .env rather than blocking the deploy.
ssh "$SERVER" 'cd newgrain-bot && (./deploy/fetch-secrets.sh || echo "⚠ secret refresh failed — using existing .env") && docker compose -f docker-compose.prod.yml up -d --build bot'

echo "✅ Deployed (bot rebuilt). Watch logs: ssh $SERVER 'cd newgrain-bot && docker compose -f docker-compose.prod.yml logs -f bot'"
