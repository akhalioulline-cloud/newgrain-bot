#!/usr/bin/env bash
# Refresh prod secrets in .env from Yandex Lockbox. Runs ON the prod VM, which
# has a service account attached → it gets a short-lived IAM token from instance
# metadata (no key file on disk) and reads the Lockbox payload over the REST API
# with curl+jq (no yc CLI needed). Replaces ONLY the secret keys held in the
# Lockbox secret; all other (non-secret) config in .env is left untouched.
# Keep a sealed offline copy of the secrets (password manager) as break-glass.
set -euo pipefail
cd "$(dirname "$0")/.."

# The Lockbox secret id is NOT sensitive; override with LOCKBOX_SECRET_ID if it changes.
SECRET_ID="${LOCKBOX_SECRET_ID:-e6qavh2hnlj0fr9b73sh}"   # flagleaf-prod
META="http://169.254.169.254/computeMetadata/v1/instance/service-accounts/default/token"
PAYLOAD="https://payload.lockbox.api.cloud.yandex.net/lockbox/v1/secrets/${SECRET_ID}/payload"

command -v jq >/dev/null || { echo "✗ jq not installed."; exit 1; }
[ -f .env ] || { echo "✗ .env missing — create it with the non-secret config first."; exit 1; }

TOKEN="$(curl -sf -H 'Metadata-Flavor: Google' "$META" | jq -r .access_token)"
[ -n "$TOKEN" ] && [ "$TOKEN" != "null" ] || {
  echo "✗ no IAM token from metadata — is the service account attached to this VM?"; exit 1; }

tmp="$(mktemp)"; trap 'rm -f "$tmp"' EXIT
curl -sf -H "Authorization: Bearer $TOKEN" "$PAYLOAD" > "$tmp" || {
  echo "✗ could not read Lockbox secret $SECRET_ID (wrong id or no access)."; exit 1; }
n="$(jq -r '.entries | length' "$tmp" 2>/dev/null || echo 0)"
[ "$n" -gt 0 ] || { echo "✗ Lockbox returned no entries."; exit 1; }

cp .env .env.bak                                  # break-glass
for k in $(jq -r '.entries[].key' "$tmp"); do     # drop old lines for the secret keys
  sed -i "/^${k}=/d" .env
done
jq -r '.entries[] | "\(.key)=\(.textValue)"' "$tmp" >> .env   # append fresh values
echo "✓ refreshed $n secret(s) in .env from Lockbox (secret $SECRET_ID; backup: .env.bak)."
