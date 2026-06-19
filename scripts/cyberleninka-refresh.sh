#!/usr/bin/env bash
# Nightly resume/refresh of the CyberLeninka agronomy corpus (sub-product 3, knowledge base).
# The harvester is RESUMABLE and idempotent: it skips already-ingested article URLs, so each
# night it (a) continues any unfinished crawl and (b) picks up newly published articles.
# Guarded so a long crawl that overruns a day is never double-started.
# Owner installs the cron (see docs/knowledge-corpus-strategy.md / the deploy note).
set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${PATH:-}
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

COMPOSE="docker compose -f docker-compose.prod.yml"
LOG="$HOME/cyberleninka-refresh.log"
NAME="cl_harvest_cron"

# Skip if ANY harvest container (manual cl_harvest or a prior cron run) is still running.
if docker ps --format '{{.Names}}' | grep -q 'cl_harvest'; then
  echo "$(date -Is) refresh skipped — a harvest is already running" >> "$LOG"
  exit 0
fi

docker rm -f "$NAME" >/dev/null 2>&1 || true
echo "$(date -Is) refresh start" >> "$LOG"
$COMPOSE run --rm --name "$NAME" -T -e PYTHONPATH=/app bot \
  python -m catalog.ingest_cyberleninka --delay 2.5 >> "$LOG" 2>&1
echo "$(date -Is) refresh done" >> "$LOG"
