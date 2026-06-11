#!/usr/bin/env bash
# THREAD-OUT — run on the machine you are LEAVING, to send this session's
# verbatim transcript (.jsonl) to the other Mac over Taildrop.
# Optional: only needed when you want the exact scrollback on the other machine
# (the context itself travels via `make handoff`). Best run after you've exited
# the Claude session so the copy is complete.
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

TS="$(command -v tailscale || echo /Applications/Tailscale.app/Contents/MacOS/Tailscale)"
[ -x "$TS" ] || { echo "✗ Tailscale CLI not found. Is Tailscale installed?"; exit 1; }

JSONL="$(ls -t "$HOME/.claude/projects/"*newgrain*/*.jsonl 2>/dev/null | head -1 || true)"
[ -n "$JSONL" ] || { echo "✗ No session transcript found under ~/.claude/projects/*newgrain*"; exit 1; }

# the other macOS device on the tailnet (not this one) — use its tailnet name
# (DNSName short form), which Taildrop accepts, not the human display HostName.
OTHER="$("$TS" status --json 2>/dev/null | python3 -c "import sys,json
d=json.load(sys.stdin)
def n(p):
    return (p.get('DNSName','').split('.')[0]) or (p.get('TailscaleIPs') or [''])[0]
print(next((n(p) for p in d.get('Peer',{}).values() if p.get('OS')=='macOS'), ''))" 2>/dev/null || true)"
[ -n "$OTHER" ] || { echo "✗ No other macOS device on the tailnet. Is the other Mac on Tailscale and connected?"; exit 1; }

echo "→ Sending $(basename "$JSONL") ($(du -h "$JSONL" | cut -f1)) to ${OTHER}…"
"$TS" file cp "$JSONL" "${OTHER}:"
echo ""
echo "✅ Thread sent to ${OTHER}. On that machine, run:   make thread-in"
