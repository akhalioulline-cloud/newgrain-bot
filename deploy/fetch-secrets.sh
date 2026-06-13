#!/usr/bin/env bash
# Refresh prod secrets in .env from Yandex Lockbox — so secrets are no longer
# hand-copied between machines. Runs ON the prod VM (which has a service account
# attached → gets IAM tokens from instance metadata, no key file on disk). On a
# dev machine it works after a one-time `yc init` (OAuth login).
#
# Safe by design: it only replaces the SECRET keys present in Lockbox; all other
# (non-secret) config already in .env is left untouched. Keep a sealed offline
# copy of the secrets (password manager) as break-glass.
#
# Prereqs (one-time, see docs/SECRETS_LOCKBOX.md):
#   - Lockbox secret created with one entry per secret (key = env name).
#   - The VM's service account granted lockbox.payloadViewer on that secret.
#   - `yc` and `jq` installed on the host.
# Usage:  LOCKBOX_SECRET_ID=<id> ./deploy/fetch-secrets.sh
set -euo pipefail
cd "$(dirname "$0")/.."

SECRET_ID="${LOCKBOX_SECRET_ID:-}"
[ -n "$SECRET_ID" ] || { echo "✗ Set LOCKBOX_SECRET_ID (the Lockbox secret id)."; exit 1; }
command -v yc >/dev/null || { echo "✗ yc CLI not installed on this host."; exit 1; }
command -v jq >/dev/null || { echo "✗ jq not installed on this host."; exit 1; }
[ -f .env ] || { echo "✗ .env missing — create it with the non-secret config first."; exit 1; }

echo "→ fetching secrets from Lockbox $SECRET_ID…"
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
yc lockbox payload get --id "$SECRET_ID" --format json > "$tmp"

# Replace only the secret keys; preserve all other lines in .env.
cp .env .env.bak
for k in $(jq -r '.entries[].key' "$tmp"); do
  sed -i "/^${k}=/d" .env
done
jq -r '.entries[] | "\(.key)=\(.text_value)"' "$tmp" >> .env
echo "✓ refreshed $(jq -r '.entries|length' "$tmp") secret(s) in .env from Lockbox (backup: .env.bak)."
