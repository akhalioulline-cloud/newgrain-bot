#!/usr/bin/env bash
# DEPLOY — rsync the repo to the prod VM and rebuild the bot image.
# Code is BAKED into the image, so a plain restart keeps old code — we rebuild.
# ⚠️ Avoid running this while the agronomist is actively uploading: the bot
# restart can drop an in-flight tap.
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVER="newgrain@158.160.46.89"

echo "→ rsync repo → prod…"
rsync -az --exclude '.git' --exclude '.env' --exclude '__pycache__' --exclude '*.pyc' \
      --exclude '.claude' --exclude '.DS_Store' ./ "$SERVER:/home/newgrain/newgrain-bot/"

echo "→ rebuild + restart bot…"
ssh "$SERVER" 'cd newgrain-bot && docker compose -f docker-compose.prod.yml up -d --build bot'

echo "✅ Deployed (bot rebuilt). Watch logs: ssh $SERVER 'cd newgrain-bot && docker compose -f docker-compose.prod.yml logs -f bot'"
