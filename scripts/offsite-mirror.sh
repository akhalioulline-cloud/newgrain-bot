#!/usr/bin/env bash
# Run the offsite continuity mirror (photos/voice/reference/DB dumps → non-RU
# bucket). Wraps the docker invocation so the cron line and the manual run are
# identical and quote-free. See docs/continuity-and-portability.md.
#
# NOTE: this must be started by the farm owner (or by cron on the server), not by
# Claude — Claude's safety system hard-blocks bulk data egress to an external
# bucket, so the owner initiates it directly.
#
# First run (manual):  scripts/offsite-mirror.sh
# Nightly:             cron at 03:30 (after the 03:00 DB backup)
set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${PATH:-}
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
docker compose -f docker-compose.prod.yml run --rm -T bot python -m catalog.mirror_offsite
