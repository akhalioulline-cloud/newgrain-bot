#!/usr/bin/env bash
# Nightly Postgres backup → local disk (7-day rotation) + Yandex Object Storage.
# Installed on the prod VM at /home/newgrain/newgrain-bot/backup.sh, run by cron 03:00.
set -euo pipefail
cd "$(dirname "$0")"
COMPOSE="docker compose -f docker-compose.prod.yml"
BACKUP_DIR=/home/newgrain/backups
mkdir -p "$BACKUP_DIR"
STAMP=$(date +%Y%m%d-%H%M)
FILE="$BACKUP_DIR/newgrain-$STAMP.sql.gz"

# 1. Dump and gzip to local disk.
$COMPOSE exec -T postgres pg_dump -U newgrain -d newgrain | gzip > "$FILE"

# 2. Upload to Object Storage under backups/ via the bot container's boto3.
$COMPOSE exec -T -e KEY="backups/newgrain-$STAMP.sql.gz" bot python -c '
import os, sys, boto3
from botocore.client import Config
s3 = boto3.client("s3", endpoint_url=os.environ["S3_ENDPOINT"],
                  aws_access_key_id=os.environ["S3_ACCESS_KEY"],
                  aws_secret_access_key=os.environ["S3_SECRET_KEY"],
                  region_name=os.environ["S3_REGION"],
                  config=Config(signature_version="s3v4"))
s3.put_object(Bucket=os.environ["S3_BUCKET"], Key=os.environ["KEY"], Body=sys.stdin.buffer.read())
print("uploaded", os.environ["KEY"])
' < "$FILE"

# 3. Rotate: keep last 7 local dumps.
ls -1t "$BACKUP_DIR"/newgrain-*.sql.gz | tail -n +8 | xargs -r rm -f
echo "backup done: $FILE"
