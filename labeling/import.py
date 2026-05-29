"""Import a CVAT-annotated batch back into the labels table (Stage 2 MVP).

Run from the founder's Mac, piping the CVAT export zip through SSH:

    cat cvat-export.zip | ssh newgrain@158.160.46.89 \\
        'cd newgrain-bot && docker compose -f docker-compose.prod.yml run --rm -T bot \\
         python -m labeling.import'

The CVAT export must be in the "CVAT for Images 1.1" format (the default
when you click "Export Job" → "CVAT for images 1.1" in the CVAT UI). That
gives a zip containing annotations.xml with per-image <box> entries.

What it does:
  1. Reads annotations.xml from the input zip.
  2. Converts pixel xtl/ytl/xbr/ybr → YOLO-normalized (cx, cy, w, h).
  3. DELETEs any prior labels for the affected submissions and INSERTs
     the new ones — re-importing a corrected batch is safe (idempotent).
  4. Flips submission status: in_labeling → labeled for any submission
     that received ≥1 box. Unannotated images keep in_labeling for
     follow-up (e.g. annotator flagged as ambiguous).
"""
import asyncio
import io
import sys
import zipfile
from collections import defaultdict
from xml.etree import ElementTree as ET

from sqlalchemy import text

from bot.db import engine


def _parse_cvat_xml(xml_bytes: bytes):
    """Yields (submission_id, [(class, cx, cy, w, h), ...]) per annotated image.

    Image filename convention: {submission_id}{ext} — strip the extension
    to recover the UUID. Skips any image with malformed metadata or no boxes.
    """
    root = ET.fromstring(xml_bytes)
    by_sid: dict[str, list] = defaultdict(list)
    images_with_no_boxes = 0
    skipped_malformed = 0

    for img in root.findall("image"):
        try:
            sid = img.get("name").rsplit(".", 1)[0]
            w = float(img.get("width"))
            h = float(img.get("height"))
        except (TypeError, ValueError, AttributeError):
            skipped_malformed += 1
            continue

        boxes = img.findall("box")
        if not boxes:
            images_with_no_boxes += 1
            continue

        for box in boxes:
            try:
                label = box.get("label")
                xtl, ytl = float(box.get("xtl")), float(box.get("ytl"))
                xbr, ybr = float(box.get("xbr")), float(box.get("ybr"))
            except (TypeError, ValueError):
                continue
            bw = (xbr - xtl) / w
            bh = (ybr - ytl) / h
            if bw <= 0 or bh <= 0:
                continue
            cx = (xtl + xbr) / (2 * w)
            cy = (ytl + ybr) / (2 * h)
            by_sid[sid].append((label, cx, cy, bw, bh))

    return by_sid, images_with_no_boxes, skipped_malformed


async def _import_zip(zip_bytes: bytes) -> int:
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            xml_data = zf.read("annotations.xml")
    except (zipfile.BadZipFile, KeyError):
        print("ERROR: input must be a CVAT 'CVAT for Images 1.1' export zip "
              "with annotations.xml at the top level.", file=sys.stderr)
        return 1

    by_sid, no_boxes, malformed = _parse_cvat_xml(xml_data)

    if not by_sid:
        print(f"No annotated images found in the zip "
              f"({no_boxes} had no boxes, {malformed} malformed). Nothing to import.",
              file=sys.stderr)
        return 1

    sids = list(by_sid.keys())
    async with engine.connect() as conn:
        existing = await conn.execute(text(
            "SELECT id::text FROM submissions WHERE id::text = ANY(:ids)"
        ), {"ids": sids})
        existing_ids = {r[0] for r in existing.fetchall()}

    missing = set(sids) - existing_ids
    if missing:
        print(f"WARNING: {len(missing)} annotated image(s) have no matching "
              f"submission, skipping: {sorted(missing)[:3]}…", file=sys.stderr)

    valid_sids = sorted(existing_ids)
    total_boxes = sum(len(by_sid[s]) for s in valid_sids)

    async with engine.begin() as conn:
        # Idempotent re-import: drop prior labels for these submissions.
        await conn.execute(text(
            "DELETE FROM labels WHERE submission_id::text = ANY(:ids)"
        ), {"ids": valid_sids})

        for sid in valid_sids:
            for label, cx, cy, bw, bh in by_sid[sid]:
                await conn.execute(text(
                    """
                    INSERT INTO labels
                        (submission_id, class_label,
                         bbox_x, bbox_y, bbox_w, bbox_h,
                         annotator, source)
                    VALUES (:sid, :label, :x, :y, :w, :h, 'human', 'cvat')
                    """
                ), {"sid": sid, "label": label, "x": cx, "y": cy, "w": bw, "h": bh})

        await conn.execute(text(
            "UPDATE submissions SET status='labeled', updated_at=NOW() "
            "WHERE id::text = ANY(:ids)"
        ), {"ids": valid_sids})

    print(f"Imported {total_boxes} label(s) for {len(valid_sids)} submission(s); "
          f"flipped to status=labeled.", file=sys.stderr)
    if no_boxes:
        print(f"Note: {no_boxes} image(s) in the batch had zero boxes — "
              f"they stay at status=in_labeling for follow-up.", file=sys.stderr)
    return 0


def main() -> int:
    zip_bytes = sys.stdin.buffer.read()
    if not zip_bytes:
        print("ERROR: no data on stdin. Pipe a CVAT 'CVAT for Images 1.1' export "
              "zip into this command.", file=sys.stderr)
        return 1
    return asyncio.run(_import_zip(zip_bytes))


if __name__ == "__main__":
    sys.exit(main())
