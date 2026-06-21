#!/usr/bin/env bash
# HANDOFF — run this on the machine you are LEAVING.
# Saves Claude Code's project memory into the repo, then commits + pushes
# everything (code + context) so the other machine can pick up exactly where
# you left off. Run it from anywhere inside the repo.
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "→ Saving Claude context snapshot…"
./scripts/claude-memory.sh save

# Mirror the memory snapshot (plain markdown — safe, no .git) to iCloud so the iPhone
# Claude can ATTACH it to a chat for pickup (it has no GitHub connector). macOS only;
# silently skipped where iCloud Drive isn't present.
ICLOUD_DOCS="$HOME/Library/Mobile Documents/com~apple~CloudDocs"
if [ -d "$ICLOUD_DOCS" ]; then
  mkdir -p "$ICLOUD_DOCS/Flagleaf_context"
  cp docs/claude-context/*.md "$ICLOUD_DOCS/Flagleaf_context/" 2>/dev/null \
    && echo "→ Mirrored memory to iCloud → Flagleaf_context (for iPhone pickup)"
fi

echo "→ Changes being handed off:"
git status --short || true

git add -A
git commit -m "handoff: $(date '+%Y-%m-%d %H:%M')" || echo "  (no new code/context to commit)"
git push origin main
echo ""
echo "✅ Handed off. On the OTHER machine, run:"
echo "      cd ~/newgrain-bot && git pull origin main && ./scripts/pickup.sh"
echo "   (the 'git pull' bootstraps the scripts if that machine's clone is stale)"
