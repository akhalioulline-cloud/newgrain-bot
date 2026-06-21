#!/usr/bin/env bash
# Sync Claude Code's project memory between this repo (a portable snapshot under
# docs/claude-context/) and the machine-local live memory dir, so the working
# context follows you across machines.
#
#   ./scripts/claude-memory.sh restore   # repo snapshot  -> ~/.claude  (new machine)
#   ./scripts/claude-memory.sh save      # ~/.claude -> repo snapshot   (before committing)
#
# Claude Code keys its memory by the project directory path, encoded with "/"->"-".
# Run this from the repo root (where you also run `claude`).
#
# `save` auto-discovers ALL project memory files (so new ones sync automatically),
# EXCEPT personal/unrelated ones in the exclude list below. This used to be a
# hardcoded allowlist that went stale — new memories silently stopped syncing.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SNAP="$REPO_ROOT/docs/claude-context"
ENC="$(printf '%s' "$REPO_ROOT" | sed 's#/#-#g')"
LIVE="$HOME/.claude/projects/$ENC/memory"

# Personal/unrelated memories that must NEVER be committed to this repo.
# Add filenames here (anything with a `personal-` prefix is always excluded too).
EXCLUDE="personal-vpn-server.md flagleaf-site.md"

_excluded() {
  local f="$1"
  case "$f" in personal-*) return 0;; esac
  case " $EXCLUDE " in *" $f "*) return 0;; esac
  return 1
}

case "${1:-}" in
  restore)
    [ -d "$SNAP" ] || { echo "No snapshot at $SNAP — nothing to restore."; exit 1; }
    mkdir -p "$LIVE"
    n=0
    for src in "$SNAP"/*.md; do
      f="$(basename "$src")"
      _excluded "$f" && continue
      cp "$src" "$LIVE/$f"; n=$((n+1))
    done
    echo "Restored $n file(s) -> $LIVE"
    echo "Start Claude Code from $REPO_ROOT and the context will load."
    ;;
  save)
    [ -d "$LIVE" ] || { echo "No live memory at $LIVE — nothing to save."; exit 1; }
    mkdir -p "$SNAP"
    n=0; skipped=0
    for src in "$LIVE"/*.md; do
      f="$(basename "$src")"
      if _excluded "$f"; then echo "  skip (personal) $f"; skipped=$((skipped+1)); continue; fi
      cp "$src" "$SNAP/$f"; echo "  saved $f"; n=$((n+1))
    done
    echo "Updated $n file(s) in docs/claude-context/ (skipped $skipped personal)."
    echo "Review, then: git add docs/claude-context && git commit"
    ;;
  *)
    echo "Usage: $0 {restore|save}"
    exit 1
    ;;
esac
