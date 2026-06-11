#!/usr/bin/env bash
# THREAD-IN — run on the machine you ARRIVED at, to receive the verbatim
# transcript sent by `make thread-out` and file it so `claude --resume` sees it.
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO="$(pwd)"

TS="$(command -v tailscale || echo /Applications/Tailscale.app/Contents/MacOS/Tailscale)"
[ -x "$TS" ] || { echo "✗ Tailscale CLI not found. Is Tailscale installed?"; exit 1; }

echo "→ Pulling Taildrop files into ~/Downloads…"
"$TS" file get "$HOME/Downloads/" 2>/dev/null || true

JSONL="$(ls -t "$HOME/Downloads/"*.jsonl 2>/dev/null | head -1 || true)"
[ -n "$JSONL" ] || { echo "✗ No .jsonl in ~/Downloads. Did the Taildrop arrive? (Tailscale must be Connected; re-run 'make thread-out' on the other Mac.)"; exit 1; }

# Claude Code's project folder = the repo's absolute path with '/' -> '-'
ENC="$(echo "$REPO" | sed 's#/#-#g')"
DEST="$HOME/.claude/projects/$ENC"
mkdir -p "$DEST"
mv "$JSONL" "$DEST/"
echo ""
echo "✅ Filed $(basename "$JSONL") into this project."
echo "   Now run:   claude --resume      (pick that session for the full scrollback)"
