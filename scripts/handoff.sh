#!/usr/bin/env bash
# HANDOFF — run this on the machine you are LEAVING.
# Saves Claude Code's project memory into the repo, then commits + pushes
# everything (code + context) so the other machine can pick up exactly where
# you left off. Run it from anywhere inside the repo.
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "→ Saving Claude context snapshot…"
./scripts/claude-memory.sh save

echo "→ Changes being handed off:"
git status --short || true

git add -A
git commit -m "handoff: $(date '+%Y-%m-%d %H:%M')" || echo "  (no new code/context to commit)"
git push origin main
echo ""
echo "✅ Handed off. On the OTHER machine, run:   ./scripts/pickup.sh"
