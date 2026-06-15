"""Mirror the photos (and voice notes) from Yandex Object Storage to an OFFSITE,
non-RU bucket — the continuity archive. So if the RU internet is cut off, the
irreplaceable training data already lives abroad and the system can be rebuilt
on GCP/AWS from GitHub + this archive (see docs/continuity-and-portability.md).

Incremental: copies only keys not already in the offsite bucket. No-op (exit 0)
until OFFSITE_S3_* is configured, so it's safe to wire into cron before the
offsite account exists.

Source (Yandex):  S3_ENDPOINT / S3_BUCKET / S3_ACCESS_KEY / S3_SECRET_KEY
Offsite (abroad): OFFSITE_S3_ENDPOINT / OFFSITE_S3_BUCKET / OFFSITE_S3_ACCESS_KEY
                  / OFFSITE_S3_SECRET_KEY  [/ OFFSITE_S3_REGION]

Run:  python -m catalog.mirror_offsite
"""
import os
import sys

import boto3
from botocore.client import Config

PREFIXES = ("raw/", "voice/", "reference/", "backups/")  # photos, voice, sheets, db dumps


def _client(endpoint, key, secret, region):
    return boto3.client(
        "s3", endpoint_url=endpoint, aws_access_key_id=key,
        aws_secret_access_key=secret, region_name=region or "us-east-1",
        config=Config(signature_version="s3v4"),
    )


def main() -> int:
    off_ep = os.environ.get("OFFSITE_S3_ENDPOINT")
    off_bucket = os.environ.get("OFFSITE_S3_BUCKET")
    off_key = os.environ.get("OFFSITE_S3_ACCESS_KEY")
    off_secret = os.environ.get("OFFSITE_S3_SECRET_KEY")
    if not (off_ep and off_bucket and off_key and off_secret):
        print("offsite mirror not configured (OFFSITE_S3_* unset) — skipping.",
              file=sys.stderr)
        return 0

    src = _client(os.environ["S3_ENDPOINT"], os.environ["S3_ACCESS_KEY"],
                  os.environ["S3_SECRET_KEY"], os.environ.get("S3_REGION"))
    src_bucket = os.environ["S3_BUCKET"]
    dst = _client(off_ep, off_key, off_secret, os.environ.get("OFFSITE_S3_REGION"))

    copied = skipped = failed = 0
    paginator = src.get_paginator("list_objects_v2")
    for prefix in PREFIXES:
        for page in paginator.paginate(Bucket=src_bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                key, size = obj["Key"], obj["Size"]
                try:
                    dst.head_object(Bucket=off_bucket, Key=key)
                    skipped += 1
                    continue            # already mirrored
                except Exception:
                    pass
                try:
                    body = src.get_object(Bucket=src_bucket, Key=key)["Body"].read()
                    dst.put_object(Bucket=off_bucket, Key=key, Body=body)
                    copied += 1
                except Exception as exc:
                    failed += 1
                    print(f"  mirror failed {key}: {exc}", file=sys.stderr)

    print(f"offsite mirror: copied {copied}, already-present {skipped}, failed {failed}.",
          file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
