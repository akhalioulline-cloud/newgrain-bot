"""Export labeled weed photos + our species list as a SELF-CONTAINED bake-off
bundle (images base64-embedded), so the bake-off can run on a machine without
prod-storage access (e.g. the Mac, which only needs the LLM APIs).

Run in the prod bot container; capture stdout to a local file:
  docker compose -f docker-compose.prod.yml run --rm -T bot python -m catalog.weedid_export > bundle.json
"""
import asyncio
import base64
import json
import os
import sys
from urllib.parse import urlparse

import boto3
from botocore.client import Config
from sqlalchemy import text

from bot.db import engine


def _s3():
    ep = os.environ["S3_ENDPOINT"]
    ep = ep if ep.startswith("http") else "https://" + ep
    return boto3.client("s3", endpoint_url=ep, aws_access_key_id=os.environ["S3_ACCESS_KEY"],
                        aws_secret_access_key=os.environ["S3_SECRET_KEY"],
                        region_name=os.environ.get("S3_REGION", "ru-central1"),
                        config=Config(signature_version="s3v4"))


async def main():
    async with engine.connect() as c:
        subs = (await c.execute(text(
            "SELECT id::text, subcategory, image_url FROM submissions "
            "WHERE category='weed' AND subcategory IS NOT NULL AND subcategory<>'' "
            "AND image_url IS NOT NULL ORDER BY created_at"))).all()
        sp = (await c.execute(text(
            "SELECT latin_name, russian_name FROM weed_species ORDER BY russian_name"))).all()
    cl = _s3()
    out = []
    for sid, label, url in subs:
        p = urlparse(url)
        try:
            b = cl.get_object(Bucket=p.netloc, Key=p.path.lstrip("/"))["Body"].read()
        except Exception as e:
            print(f"skip {sid}: {e}", file=sys.stderr)
            continue
        out.append({"id": sid, "label": label, "b64": base64.b64encode(b).decode()})
    print(json.dumps({"subs": out, "species": [{"latin": l, "ru": r} for l, r in sp]}))
    print(f"bundled {len(out)} photos, {len(sp)} species", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
