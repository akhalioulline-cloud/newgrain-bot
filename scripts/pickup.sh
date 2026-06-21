#!/usr/bin/env bash
# PICKUP — run this on the machine you are ARRIVING at.
# Pulls the latest code + context, then restores Claude Code's memory so a
# fresh `claude` session knows everything. Run it from anywhere inside the repo.
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "→ Pulling latest code + context…"
git pull origin main

echo "→ Restoring Claude context…"
./scripts/claude-memory.sh restore
echo ""
echo "✅ Picked up. Now start Claude from this folder:   claude"
echo "   (then ask it: 'what are the open threads on Flagleaf?')"
INBOX="$HOME/Library/Mobile Documents/com~apple~CloudDocs/Flagleaf_inbox"
if [ -n "$(ls -A "$INBOX" 2>/dev/null | grep -v '^_README.md$' || true)" ]; then
  echo "📥 iPhone handoff waiting in iCloud → Flagleaf_inbox — tell Claude to check it."
fi
