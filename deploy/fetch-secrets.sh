#!/usr/bin/env bash
# Refresh secrets in .env from Yandex Lockbox. Works in two places:
#  - on the prod VM: uses the attached service account's IAM token from instance
#    metadata + the Lockbox REST API (no yc CLI, no key file on disk).
#  - on a dev laptop: falls back to the `yc` CLI (one-time `yc init` OAuth login).
# Replaces ONLY the secret keys held in the Lockbox secret; other (non-secret)
# config in .env is left untouched. Keep a sealed offline copy as break-glass.
set -euo pipefail
cd "$(dirname "$0")/.."

# The Lockbox secret id is NOT sensitive; override with LOCKBOX_SECRET_ID if it changes.
SECRET_ID="${LOCKBOX_SECRET_ID:-e6qavh2hnlj0fr9b73sh}"   # flagleaf-prod
META="http://169.254.169.254/computeMetadata/v1/instance/service-accounts/default/token"
PAYLOAD="https://payload.lockbox.api.cloud.yandex.net/lockbox/v1/secrets/${SECRET_ID}/payload"

command -v jq >/dev/null || { echo "✗ jq not installed."; exit 1; }
[ -f .env ] || { echo "✗ .env missing — create it from .env.example first."; exit 1; }

tmp="$(mktemp)"; trap 'rm -f "$tmp"' EXIT

# Prefer VM instance metadata; fall back to yc (laptop).
TOKEN="$(curl -sf -m 2 -H 'Metadata-Flavor: Google' "$META" 2>/dev/null | jq -r '.access_token // empty' 2>/dev/null || true)"
if [ -n "$TOKEN" ]; then
  echo "→ reading Lockbox via VM service account (metadata)…"
  curl -sf -H "Authorization: Bearer $TOKEN" "$PAYLOAD" > "$tmp" \
    || { echo "✗ Lockbox read failed (wrong id or no access)."; exit 1; }
else
  command -v yc >/dev/null || {
    echo "✗ Not on the prod VM and 'yc' is not installed."
    echo "  Laptop setup: install yc + run 'yc init' (see SETUP.md), then re-run."; exit 1; }
  echo "→ reading Lockbox via yc (laptop)…"
  yc lockbox payload get --id "$SECRET_ID" --format json > "$tmp" \
    || { echo "✗ yc lockbox read failed — run 'yc init' (OAuth) and ensure access."; exit 1; }
fi

n="$(jq -r '.entries | length' "$tmp" 2>/dev/null || echo 0)"
[ "$n" -gt 0 ] || { echo "✗ Lockbox returned no entries."; exit 1; }

# Replace only the secret keys; preserve all other lines. Portable (no sed -i,
# which differs GNU vs BSD/macOS).
keys="$(jq -r '.entries[].key' "$tmp" | paste -sd'|' -)"
cp .env .env.bak
grep -vE "^(${keys})=" .env > .env.new || true
mv .env.new .env
# REST returns .textValue, yc returns .text_value — accept either.
jq -r '.entries[] | "\(.key)=\(.textValue // .text_value)"' "$tmp" >> .env
echo "✓ refreshed $n secret(s) in .env from Lockbox (secret $SECRET_ID; backup: .env.bak)."
