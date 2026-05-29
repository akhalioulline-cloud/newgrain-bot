"""Export ready_for_labeling submissions as a CVAT-ingest zip.

Run from the founder's Mac, streaming the zip back through SSH:

    ssh newgrain@158.160.46.89 \\
        'cd newgrain-bot && docker compose -f docker-compose.prod.yml run --rm -T bot \\
         python -m labeling.export' > batch.zip

What it does:
  1. Queries submissions WHERE status='ready_for_labeling'.
  2. Downloads each photo from Object Storage.
  3. Packages images + manifest.csv into a zip (streamed to stdout).
  4. Flips status of exported rows ready_for_labeling → in_labeling so
     the next export is a clean no-op until new photos arrive.

The annotator then uploads the zip to a new task in the CVAT Cloud
weeds-diseases-stress project and labels using the existing 31-class schema.
Bring results back via labeling/import.py.
"""
import asyncio
import csv
import io
import sys
import zipfile
from pathlib import Path

from sqlalchemy import text

from bot.config import settings
from bot.db import engine
from bot.storage import _client  # noqa: F401 — internal boto3 client


async def _export_to_stream(out_stream) -> int:
    async with engine.connect() as conn:
        result = await conn.execute(text(
            """
            SELECT s.id, s.image_url, s.category, s.subcategory,
                   s.comment_text, s.comment_voice_text,
                   f.name AS field_name, f.crop
            FROM submissions s
            LEFT JOIN fields f ON f.id = s.field_id
            WHERE s.status = 'ready_for_labeling'
            ORDER BY s.created_at
            """
        ))
        rows = result.mappings().all()

    if not rows:
        print("Nothing to export — no submissions at status=ready_for_labeling.",
              file=sys.stderr)
        return 0

    print(f"Packaging {len(rows)} submission(s)…", file=sys.stderr)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        manifest = io.StringIO()
        writer = csv.writer(manifest)
        writer.writerow([
            "submission_id", "image", "field", "crop", "category",
            "species_hint", "comment",
        ])

        for r in rows:
            sid = str(r["id"])
            s3_key = r["image_url"].replace(f"s3://{settings.s3_bucket}/", "")
            ext = Path(s3_key).suffix or ".jpg"
            img_filename = f"{sid}{ext}"

            obj = _client.get_object(Bucket=settings.s3_bucket, Key=s3_key)
            zf.writestr(f"images/{img_filename}", obj["Body"].read())

            comment = (r["comment_text"] or r["comment_voice_text"] or "").strip()
            writer.writerow([
                sid, img_filename, r["field_name"] or "", r["crop"] or "",
                r["category"] or "", r["subcategory"] or "", comment,
            ])

        zf.writestr("manifest.csv", manifest.getvalue())

    # Mark these as "in_labeling" so re-running won't re-export them.
    ids = [r["id"] for r in rows]
    async with engine.begin() as conn:
        await conn.execute(text(
            "UPDATE submissions SET status='in_labeling', updated_at=NOW() "
            "WHERE id = ANY(:ids)"
        ), {"ids": ids})

    out_stream.write(buf.getvalue())
    print(f"Exported {len(rows)} submission(s); flipped to status=in_labeling.",
          file=sys.stderr)
    return len(rows)


def main() -> int:
    n = asyncio.run(_export_to_stream(sys.stdout.buffer))
    return 0 if n > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
