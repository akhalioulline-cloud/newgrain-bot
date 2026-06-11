#!/usr/bin/env bash
# Sync Claude Code's project memory between this repo (a portable snapshot under
# docs/claude-context/) and the machine-local live memory dir, so the working
# context follows you across machines.
#
#   ./scripts/claude-memory.sh restore   # repo snapshot  -> ~/.claude  (new machine)
#   ./scripts/claude-memory.sh save      # ~/.claude -> repo snapshot   (before committing)
#
# Claude Code keys its memory by the project directory path, encoded with "/"->"-".
# Run this from the repo root (where you also run `claude`). Personal/unrelated
# memories (VPN server, the separate marketing-site repo) are never synced.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SNAP="$REPO_ROOT/docs/claude-context"
ENC="$(printf '%s' "$REPO_ROOT" | sed 's#/#-#g')"
LIVE="$HOME/.claude/projects/$ENC/memory"

# Project memory files we sync (allowlist — excludes personal-vpn-server.md and
# flagleaf-site.md, which are not this project's context).
FILES=(
  newgrain-goal-and-principle.md
  newgrain-labeling-pipeline.md
  newgrain-photo-attribution.md
  newgrain-prod-deploy.md
  newgrain-status-2026-05.md
  user-nontechnical-founder.md
  workflow-decisions-vs-code.md
)

case "${1:-}" in
  restore)
    mkdir -p "$LIVE"
    cp "$SNAP"/*.md "$LIVE"/
    echo "Restored $(ls "$SNAP"/*.md | wc -l | tr -d ' ') file(s) -> $LIVE"
    echo "Start Claude Code from $REPO_ROOT and the context will load."
    ;;
  save)
    [ -d "$LIVE" ] || { echo "No live memory at $LIVE — nothing to save."; exit 1; }
    n=0
    for f in "${FILES[@]}"; do
      if [ -f "$LIVE/$f" ]; then cp "$LIVE/$f" "$SNAP/$f"; echo "  saved $f"; n=$((n+1)); fi
    done
    echo "Updated $n file(s) in docs/claude-context/. Review, then: git add docs/claude-context && git commit"
    ;;
  *)
    echo "Usage: $0 {restore|save}"
    exit 1
    ;;
esac
