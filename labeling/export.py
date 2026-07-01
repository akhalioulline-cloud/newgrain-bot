"""Export ready_for_labeling submissions to CVAT (default) or as a zip (--zip-only).

Default mode — auto-upload to CVAT:
    ssh newgrain@111.88.248.159 \\
        'cd newgrain-bot && docker compose -f docker-compose.prod.yml run --rm bot \\
         python -m labeling.export'

    1. Queries submissions WHERE status='ready_for_labeling'.
    2. Downloads each photo from Object Storage to a temp dir.
    3. Creates a CVAT task in CVAT_PROJECT_NAME (default: weeds-diseases-stress)
       named batch-YYYYMMDD, uploads images directly via the CVAT REST API.
    4. Flips status ready_for_labeling → in_labeling ONLY after the upload
       succeeds — so a network error doesn't strand data in a half-done state.
    5. Prints the task URL on stderr; click through to annotate.

Zip-only mode (manual fallback / offline backup):
    ssh newgrain@111.88.248.159 \\
        'cd newgrain-bot && docker compose -f docker-compose.prod.yml run --rm -T bot \\
         python -m labeling.export --zip-only' > batch.zip

    Writes the legacy zip to stdout (images/ + manifest.csv). Does NOT flip
    status — so a subsequent auto-upload picks up the same rows. Use when
    CVAT is unreachable, or to keep a local archive of the batch.
"""
import argparse
import asyncio
import csv
import io
import re
import sys
import tempfile
import zipfile
from datetime import date
from pathlib import Path

from sqlalchemy import text

from bot.config import settings
from bot.db import engine
from bot.storage import _client  # noqa: F401 — internal boto3 client

# Carry the agronomist's hint into CVAT so the annotator knows which class to
# pick: it goes (a) into the frame filename (visible in the annotation view)
# and (b) into the task description as a full per-frame legend.
_CAT_RU = {
    "weed": "сорняк", "disease": "болезнь", "stress": "стресс",
    "control": "контроль", "treatment_result": "результат обработки",
}
_RU2LAT = {ord(k): v for k, v in {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}.items()}


def _slugify(text_value: str, maxlen: int = 40) -> str:
    """ASCII-safe, '__'-free slug for a filename (transliterates Cyrillic).
    Latin species ('Amaranthus retroflexus' → 'amaranthus-retroflexus');
    Russian free-text ('Метлица обыкновенная' → 'metlitsa-obyknovennaya')."""
    s = (text_value or "").strip().lower().translate(_RU2LAT)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:maxlen].strip("-")


async def _fetch_pending():
    async with engine.connect() as conn:
        result = await conn.execute(text(
            """
            SELECT s.id, s.image_url, s.category, s.subcategory,
                   s.comment_text, s.comment_voice_text,
                   f.name AS field_name, f.crop
            FROM submissions s
            LEFT JOIN fields f ON f.id = s.field_id
            WHERE s.status = 'ready_for_labeling'
              AND s.category IN ('weed','disease','pest')  -- only these need CVAT boxes;
            ORDER BY s.created_at                          -- scouting/control/treatment/stress skip it
            """
        ))
        return result.mappings().all()


async def _flip_to_in_labeling(submission_ids):
    async with engine.begin() as conn:
        await conn.execute(text(
            "UPDATE submissions SET status='in_labeling', updated_at=NOW() "
            "WHERE id = ANY(:ids)"
        ), {"ids": submission_ids})


def _download_image(s3_key: str) -> bytes:
    return _client.get_object(Bucket=settings.s3_bucket, Key=s3_key)["Body"].read()


def _row_filename(r) -> str:
    """Per-row image filename: {hint-slug}__{submission_id}.{ext}, or just
    {submission_id}.{ext} when there's no hint. The slug puts the agronomist's
    species right in the CVAT frame name; import.py recovers the UUID by
    splitting on '__'."""
    sid = str(r["id"])
    s3_key = r["image_url"].replace(f"s3://{settings.s3_bucket}/", "")
    ext = Path(s3_key).suffix or ".jpg"
    slug = _slugify(r["subcategory"] or "")
    return f"{slug}__{sid}{ext}" if slug else f"{sid}{ext}"


def _build_legend(rows) -> str:
    """Per-frame legend for the CVAT task description: filename → field ·
    category · species hint · comment. Full original text (incl. Russian),
    as a backup to the slugified filename."""
    lines = ["Подсказки агронома (по имени кадра):", ""]
    for r in rows:
        cat = _CAT_RU.get(r["category"], r["category"] or "—")
        line = f"{_row_filename(r)} — {r['field_name'] or 'поле?'} · {cat}"
        species = (r["subcategory"] or "").strip()
        if species:
            line += f" · {species}"
        comment = (r["comment_text"] or r["comment_voice_text"] or "").strip()
        if comment:
            line += f" · «{comment}»"
        lines.append(line)
    return "\n".join(lines)[:4000]   # CVAT description cap; daily batches fit easily


def _build_zip(rows) -> bytes:
    """Same packaging as the pre-CVAT export — kept for --zip-only fallback."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        manifest = io.StringIO()
        writer = csv.writer(manifest)
        writer.writerow([
            "submission_id", "image", "field", "crop", "category",
            "species_hint", "comment",
        ])
        for r in rows:
            img_filename = _row_filename(r)
            s3_key = r["image_url"].replace(f"s3://{settings.s3_bucket}/", "")
            zf.writestr(f"images/{img_filename}", _download_image(s3_key))
            comment = (r["comment_text"] or r["comment_voice_text"] or "").strip()
            writer.writerow([
                str(r["id"]), img_filename, r["field_name"] or "", r["crop"] or "",
                r["category"] or "", r["subcategory"] or "", comment,
            ])
        zf.writestr("manifest.csv", manifest.getvalue())
    return buf.getvalue()


def _upload_to_cvat(rows, batch_name: str) -> tuple[int, str]:
    """Create a task in the configured CVAT project, upload images, return
    (task_id, task_url). Raises on any failure — caller flips status only
    if this returns cleanly.

    Uses raw REST (requests) instead of cvat-sdk because CVAT Cloud
    (server 2.66) is multiple versions ahead of the SDK and the SDK's
    response-type validation chokes on the newer schema. The REST
    endpoints are stable across this gap.
    """
    import requests

    if not settings.cvat_api_token:
        raise RuntimeError(
            "CVAT_API_TOKEN not set in .env. Generate one at "
            f"{settings.cvat_host}/auth/settings (Settings → Personal access tokens)."
        )

    base = settings.cvat_host
    # CVAT Cloud uses Bearer-scheme tokens (not "Token <value>" as self-hosted
    # docs show — verified empirically: Token → 401, Bearer → 200).
    headers = {"Authorization": f"Bearer {settings.cvat_api_token}"}

    def api_get(path, **params):
        r = requests.get(f"{base}/api{path}", headers=headers, params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    # 1. Resolve project name → id.
    projects_resp = api_get("/projects", search=settings.cvat_project_name)
    project = next(
        (p for p in projects_resp["results"] if p["name"] == settings.cvat_project_name),
        None,
    )
    if project is None:
        names = [p["name"] for p in projects_resp["results"]]
        raise RuntimeError(
            f"CVAT project {settings.cvat_project_name!r} not found in your "
            f"account. Available: {names}. Set CVAT_PROJECT_NAME in .env."
        )

    # 2. If the project lives in an org, scope subsequent calls to it via
    # X-Organization header — otherwise task creation fails with
    # "task and project should be in the same organization."
    org_id = project.get("organization")
    if org_id is not None:
        orgs_resp = api_get("/organizations")
        org_slug = next(
            (o["slug"] for o in orgs_resp["results"] if o["id"] == org_id), None,
        )
        if org_slug is None:
            raise RuntimeError(
                f"Project is in org id {org_id} but that org isn't visible "
                f"on your account."
            )
        headers["X-Organization"] = org_slug

    # 3. Create the task (no images yet).
    create_resp = requests.post(
        f"{base}/api/tasks",
        headers={**headers, "Content-Type": "application/json"},
        json={"name": batch_name, "project_id": project["id"],
              "description": _build_legend(rows)},
        timeout=30,
    )
    create_resp.raise_for_status()
    task = create_resp.json()
    task_id = task["id"]

    # 4. Download images from Object Storage to a temp dir, then upload them
    # in one multipart POST. CVAT processes async on its end.
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        local_paths = []
        for r in rows:
            s3_key = r["image_url"].replace(f"s3://{settings.s3_bucket}/", "")
            local = tmp / _row_filename(r)
            local.write_bytes(_download_image(s3_key))
            local_paths.append(local)

        files = []
        open_handles = []
        try:
            for i, p in enumerate(local_paths):
                fh = open(p, "rb")
                open_handles.append(fh)
                files.append((f"client_files[{i}]", (p.name, fh, "image/jpeg")))
            data = {
                "image_quality": "95",
                "use_zip_chunks": "false",
                "use_cache": "true",
            }
            upload_resp = requests.post(
                f"{base}/api/tasks/{task_id}/data",
                headers=headers,  # no Content-Type — requests sets multipart boundary
                files=files,
                data=data,
                timeout=120,
            )
            upload_resp.raise_for_status()
        finally:
            for fh in open_handles:
                fh.close()

    return task_id, f"{base}/tasks/{task_id}"


async def _run(args) -> int:
    """All DB work happens inside this single asyncio.run() so the asyncpg
    connection pool isn't bound to a loop that already closed (the bug that
    showed up the first time we tried calling asyncio.run twice)."""
    rows = await _fetch_pending()
    if not rows:
        print("Nothing to export — no submissions at status=ready_for_labeling.",
              file=sys.stderr)
        return 1

    print(f"Found {len(rows)} submission(s) at ready_for_labeling.", file=sys.stderr)
    sids = [r["id"] for r in rows]

    if args.zip_only:
        print("--zip-only: writing zip to stdout; status NOT flipped.",
              file=sys.stderr)
        sys.stdout.buffer.write(_build_zip(rows))
        return 0

    batch_name = args.batch_name or f"batch-{date.today():%Y%m%d}"
    print(f"Uploading to CVAT project {settings.cvat_project_name!r} "
          f"as task {batch_name!r}…", file=sys.stderr)
    try:
        # Sync HTTP via requests — fine to call from async; we're not yielding
        # to anyone else.
        task_id, task_url = _upload_to_cvat(rows, batch_name)
    except Exception as exc:
        print(f"ERROR: CVAT upload failed: {exc}\n"
              f"Status NOT flipped — re-run is safe.", file=sys.stderr)
        return 2

    await _flip_to_in_labeling(sids)
    print(f"✅ Created CVAT task #{task_id}: {task_url}", file=sys.stderr)
    print(f"   Flipped {len(sids)} submission(s) → in_labeling.", file=sys.stderr)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--zip-only", action="store_true",
        help="Write the zip to stdout instead of uploading to CVAT. "
             "Does NOT flip status.",
    )
    parser.add_argument(
        "--batch-name", default=None,
        help="Override task name (default: batch-YYYYMMDD).",
    )
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
