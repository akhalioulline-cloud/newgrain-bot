"""Import a CVAT-annotated batch back into the labels table (Stage 2 MVP).

Two ways to invoke:

  A. Auto-fetch from CVAT (recommended — no browser involvement):

      ssh newgrain@111.88.248.159 \\
          'cd newgrain-bot && docker compose -f docker-compose.prod.yml run --rm bot \\
           python -m labeling.import --task 2291559'

     Triggers a server-side export for that task ID, polls until ready,
     downloads the zip, and processes it. This bypasses the CVAT UI's
     fragile browser-download step (which has been observed to silently
     drop the file).

  B. Pipe a zip on stdin (fallback — when you already have the zip):

      cat cvat-export.zip | ssh newgrain@111.88.248.159 \\
          'cd newgrain-bot && docker compose -f docker-compose.prod.yml run --rm -T bot \\
           python -m labeling.import'

     The zip must be a CVAT "CVAT for Images 1.1" export with
     annotations.xml at its top level.

What it does (same for both paths):
  1. Reads annotations.xml from the zip.
  2. Converts pixel xtl/ytl/xbr/ybr → YOLO-normalized (cx, cy, w, h).
  3. DELETEs any prior labels for the affected submissions and INSERTs
     the new ones — re-importing a corrected batch is safe (idempotent).
  4. Flips submission status: in_labeling → labeled for any submission
     that received ≥1 box. Unannotated images keep in_labeling for
     follow-up (e.g. annotator flagged as ambiguous).
"""
import argparse
import asyncio
import io
import sys
import time
import zipfile
from collections import defaultdict
from xml.etree import ElementTree as ET

import requests
from sqlalchemy import text

from bot.config import settings
from bot.db import engine
from bot.push import send_push

# The CVAT label the annotator picks when a weed is real but NOT in the dictionary.
# On import such frames are held at 'needs_species' and the admins are pinged to add it.
UNKNOWN_LABEL = "unknown"


def _sid_from_name(name: str) -> str:
    """Recover the submission UUID from a CVAT frame filename. Handles both
    legacy '{sid}.{ext}' and current '{hint-slug}__{sid}.{ext}' (export.py
    now prefixes the agronomist's species hint for the annotator)."""
    n = name or ""
    stem = n.rsplit(".", 1)[0] if "." in n else n
    return stem.split("__")[-1]


def _fetch_zip_from_cvat(task_id: int) -> bytes:
    """Trigger a CVAT export for `task_id`, poll until ready, return the
    zip bytes. Sidesteps the UI's browser-download step (which has been
    seen to silently fail on CVAT Cloud).
    """
    import requests

    if not settings.cvat_api_token:
        raise RuntimeError(
            "CVAT_API_TOKEN not set in .env. Generate one at "
            f"{settings.cvat_host}/auth/settings (Settings → Personal access tokens)."
        )

    base = settings.cvat_host
    # Bearer scheme (CVAT Cloud-specific; "Token" returns 401 — verified empirically).
    headers = {"Authorization": f"Bearer {settings.cvat_api_token}"}

    # 1. Resolve the task's organization so we can scope subsequent calls.
    task_resp = requests.get(f"{base}/api/tasks/{task_id}",
                             headers=headers, timeout=30)
    task_resp.raise_for_status()
    org_id = task_resp.json().get("organization")
    if org_id is not None:
        orgs = requests.get(f"{base}/api/organizations",
                            headers=headers, timeout=30).json()
        org_slug = next(
            (o["slug"] for o in orgs["results"] if o["id"] == org_id), None,
        )
        if org_slug:
            headers["X-Organization"] = org_slug

    # 2. Trigger the server-side export. CVAT returns 202 immediately with
    # an `rq_id`; the actual zip is generated async.
    print(f"Triggering CVAT export of task {task_id}…", file=sys.stderr)
    export_resp = requests.post(
        f"{base}/api/tasks/{task_id}/dataset/export"
        "?format=CVAT+for+images+1.1&save_images=false",
        headers=headers, timeout=30,
    )
    export_resp.raise_for_status()
    rq_id = export_resp.json()["rq_id"]

    # 3. Poll the requests endpoint until our rq_id reports finished.
    print(f"Waiting for CVAT to package the export…", file=sys.stderr)
    deadline = time.monotonic() + 300  # 5 min cap; real exports take ~2–5 s
    result_url = None
    while time.monotonic() < deadline:
        time.sleep(2)
        list_resp = requests.get(
            f"{base}/api/requests?action=export",
            headers=headers, timeout=30,
        )
        list_resp.raise_for_status()
        match = next(
            (r for r in list_resp.json()["results"] if r["id"] == rq_id),
            None,
        )
        if match is None:
            continue
        if match["status"] == "failed":
            raise RuntimeError(
                f"CVAT export request failed: {match.get('message') or '(no message)'}"
            )
        if match["status"] == "finished":
            result_url = match["result_url"]
            break
    if result_url is None:
        raise RuntimeError("CVAT export timed out after 5 minutes.")

    # 4. Download the zip from the result_url.
    print(f"Downloading export zip…", file=sys.stderr)
    download_resp = requests.get(result_url, headers=headers, timeout=120)
    download_resp.raise_for_status()
    return download_resp.content


# ---------------------------------------------------------------------------
# Auto-discovery mode (--auto): pull every CVAT task the annotator has marked
# 'completed' whose submissions are still awaiting import. This is what the
# nightly cron calls — no task IDs, no browser, no human in the loop.
# ---------------------------------------------------------------------------

def _cvat_base_headers():
    if not settings.cvat_api_token:
        raise RuntimeError(
            "CVAT_API_TOKEN not set in .env. Generate one at "
            f"{settings.cvat_host}/auth/settings (Settings → Personal access tokens)."
        )
    return settings.cvat_host, {"Authorization": f"Bearer {settings.cvat_api_token}"}


def _resolve_project(base, headers):
    """Return the project id for settings.cvat_project_name. Mutates `headers`
    in place to add X-Organization when the project lives in an org (required
    for the task-list / meta calls below to be scoped correctly)."""
    import requests

    r = requests.get(f"{base}/api/projects", headers=headers,
                     params={"search": settings.cvat_project_name}, timeout=30)
    r.raise_for_status()
    project = next((p for p in r.json()["results"]
                    if p["name"] == settings.cvat_project_name), None)
    if project is None:
        names = [p["name"] for p in r.json()["results"]]
        raise RuntimeError(
            f"CVAT project {settings.cvat_project_name!r} not found. "
            f"Available: {names}. Set CVAT_PROJECT_NAME in .env.")
    org_id = project.get("organization")
    if org_id is not None:
        orgs = requests.get(f"{base}/api/organizations",
                            headers=headers, timeout=30).json()
        slug = next((o["slug"] for o in orgs["results"] if o["id"] == org_id), None)
        if slug:
            headers["X-Organization"] = slug
    return project["id"]


def _list_all_tasks(base, headers, project_id):
    """Every task in the project, any status (we decide per-task what to do)."""
    import requests

    tasks = []
    url = f"{base}/api/tasks"
    params = {"project_id": project_id, "page_size": 100}
    while url:
        r = requests.get(url, headers=headers, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        tasks.extend(data.get("results", []))
        url = data.get("next")   # full URL with params already baked in
        params = None
    return tasks


def _task_annotation_count(base, headers, task_id):
    """Total annotation shapes+tags on a task — lets us rescue labels even when
    the annotator forgot to mark the task 'Completed' (the June-2 stranding bug)."""
    import requests

    r = requests.get(f"{base}/api/tasks/{task_id}/annotations",
                     headers=headers, timeout=30)
    if r.status_code != 200:
        return 0
    d = r.json()
    return len(d.get("shapes", [])) + len(d.get("tags", []))


def _delete_task(base, headers, task_id):
    """Delete a CVAT task to recycle the slot (free tier caps the org at 3 tasks)."""
    import requests

    r = requests.delete(f"{base}/api/tasks/{task_id}", headers=headers, timeout=30)
    r.raise_for_status()


def _task_is_completed(base, headers, task_id):
    """True if the annotator finished the task. CVAT's 'Finish the job' button
    sets the JOB *state* to 'completed' — but the TASK *status* stays
    'annotation' in our single-stage workflow, so we must check the jobs, not
    task.status (the original bug: 'Finish the job' was pressed but never
    recognized as done)."""
    import requests

    r = requests.get(f"{base}/api/jobs", headers=headers,
                     params={"task_id": task_id}, timeout=30)
    r.raise_for_status()
    jobs = [j for j in r.json().get("results", []) if j.get("type") != "ground_truth"]
    return bool(jobs) and all(j.get("state") == "completed" for j in jobs)


def _task_submission_ids(base, headers, task_id):
    """Submission UUIDs for a task, read from its frame filenames ({sid}.{ext})."""
    import requests

    r = requests.get(f"{base}/api/tasks/{task_id}/data/meta",
                     headers=headers, timeout=30)
    r.raise_for_status()
    out = []
    for f in r.json().get("frames", []):
        out.append(_sid_from_name(f.get("name") or ""))
    return [s for s in out if s]


async def _count_in_labeling(sids):
    if not sids:
        return 0
    async with engine.connect() as conn:
        res = await conn.execute(text(
            "SELECT count(*) FROM submissions "
            "WHERE id::text = ANY(:ids) AND status = 'in_labeling'"
        ), {"ids": sids})
        return res.scalar_one()


async def _run_auto() -> int:
    """Nightly: pull labels back and recycle CVAT task slots.

    Per task ('done' = job state 'completed', i.e. annotator pressed
    'Finish the job' — NOT task.status, which stays 'annotation'):
      • done → import any still-pending submissions, then DELETE the task to
        free the slot (free-tier 3-task cap). If nothing is pending (already
        imported), skip the re-import — so a manual de-dup/edit isn't clobbered.
      • has annotations but NOT done → import the labels anyway (so a forgotten
        'Finish the job' can't strand work) but KEEP the task — still being worked.
      • nothing to do → leave it.
    Import is idempotent (DELETE+INSERT of labels), so re-importing is safe.
    """
    base, headers = _cvat_base_headers()
    project_id = _resolve_project(base, headers)
    tasks = _list_all_tasks(base, headers, project_id)
    if not tasks:
        print("No CVAT tasks in the project — nothing to do.", file=sys.stderr)
        return 0

    imported = recycled = rescued = skipped = failed = 0
    for t in tasks:
        tid = t["id"]
        name = t.get("name")
        try:
            completed = _task_is_completed(base, headers, tid)
            sids = _task_submission_ids(base, headers, tid)
            pending = await _count_in_labeling(sids)
            anno = _task_annotation_count(base, headers, tid)

            if completed:
                ok_to_delete = True
                if pending > 0:   # only import what's not in yet — don't clobber edits/de-dup
                    zip_bytes = _fetch_zip_from_cvat(tid)
                    rc = await _import_zip(zip_bytes)
                    if rc == 0:
                        imported += 1
                    else:
                        ok_to_delete = False  # import problem — keep, retry next run
                if ok_to_delete:
                    _delete_task(base, headers, tid)
                    recycled += 1
                    print(f"Task #{tid} ({name}): completed → imported + deleted "
                          f"(slot freed).", file=sys.stderr)
                else:
                    print(f"Task #{tid} ({name}): import failed — NOT deleted, "
                          f"will retry.", file=sys.stderr)
            elif anno > 0 and pending > 0:
                # Labeled but the annotator hasn't clicked 'Completed' — rescue
                # the labels so nothing strands; leave the task for them to finish.
                zip_bytes = _fetch_zip_from_cvat(tid)
                rc = await _import_zip(zip_bytes)
                if rc == 0:
                    rescued += 1
                print(f"Task #{tid} ({name}): {anno} annotation(s), not marked "
                      f"Completed — labels rescued, task kept.", file=sys.stderr)
            else:
                skipped += 1
        except Exception as exc:
            failed += 1
            print(f"ERROR processing task #{tid}: {exc}", file=sys.stderr)

    print(f"Auto-import done: {imported} imported, {recycled} completed+recycled, "
          f"{rescued} rescued (kept), {skipped} untouched, {failed} failed.",
          file=sys.stderr)

    # Surface meaningful activity to the admins so the pipeline is observable
    # without reading logs (failures are alerted separately by pipeline.sh).
    if imported or recycled or rescued:
        try:
            from labeling.alert import send
            send(
                f"✅ Flagleaf разметка: импортировано задач {imported}, "
                f"освобождено слотов CVAT {recycled}, спасено незавершённых {rescued}. "
                f"Метки сохранены в базе."
            )
        except Exception:
            pass

    return 0 if failed == 0 else 2


def _parse_cvat_xml(xml_bytes: bytes):
    """Parse a CVAT export. Returns:
      • by_sid       — {submission_id: [(class, cx, cy, w, h), ...]} for boxed images
      • zero_box_sids — image sids with NO box (annotator saw no weed → become scouting)
      • unknown_sids  — sids with a box labelled UNKNOWN_LABEL (weed not in the dictionary
                        → held at 'needs_species' + admins pinged to add it)
      • skipped_malformed — count of images with unreadable metadata

    Filename convention: '{hint-slug}__{submission_id}.{ext}' → _sid_from_name recovers the UUID.
    """
    root = ET.fromstring(xml_bytes)
    by_sid: dict[str, list] = defaultdict(list)
    zero_box_sids: list[str] = []
    unknown_sids: set[str] = set()
    skipped_malformed = 0

    for img in root.findall("image"):
        try:
            sid = _sid_from_name(img.get("name"))
            w = float(img.get("width"))
            h = float(img.get("height"))
        except (TypeError, ValueError, AttributeError):
            skipped_malformed += 1
            continue

        boxes = img.findall("box")
        if not boxes:
            if sid:
                zero_box_sids.append(sid)          # no weed marked → scouting (Rule A)
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
            if label == UNKNOWN_LABEL:
                unknown_sids.add(sid)              # weed not in dictionary → notify (Rule B)

    return by_sid, zero_box_sids, unknown_sids, skipped_malformed


async def _import_zip(zip_bytes: bytes) -> int:
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            xml_data = zf.read("annotations.xml")
    except (zipfile.BadZipFile, KeyError):
        print("ERROR: input must be a CVAT 'CVAT for Images 1.1' export zip "
              "with annotations.xml at the top level.", file=sys.stderr)
        return 1

    by_sid, zero_box_sids, unknown_sids, malformed = _parse_cvat_xml(xml_data)

    if not by_sid and not zero_box_sids:
        print(f"No images found in the zip ({malformed} malformed). Nothing to import.",
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
    # Split boxed submissions: known-species → 'labeled'; unknown weed → 'needs_species'.
    unknown_valid = sorted(s for s in valid_sids if s in unknown_sids)
    labeled_valid = sorted(s for s in valid_sids if s not in unknown_sids)
    total_boxes = sum(len(by_sid[s]) for s in valid_sids)

    # Loop-closing recognition (NOT points — see no-gamification spec): capture who
    # transitions to 'labeled' for the FIRST time so each agronomist is thanked once,
    # not again on idempotent re-imports. Only real (known-species) labels earn thanks.
    async with engine.connect() as conn:
        thank_rows = [dict(r) for r in (await conn.execute(text(
            "SELECT u.tg_user_id AS tg, s.subcategory AS sub "
            "FROM submissions s JOIN users u ON u.id = s.user_id "
            "WHERE s.id::text = ANY(:ids) AND s.status <> 'labeled' "
            "  AND u.tg_user_id IS NOT NULL"
        ), {"ids": labeled_valid})).mappings().all()]

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

        if labeled_valid:
            await conn.execute(text(
                "UPDATE submissions SET status='labeled', updated_at=NOW() "
                "WHERE id::text = ANY(:ids)"
            ), {"ids": labeled_valid})
        # Unknown weed: box is done, species isn't — hold until it's added to the dictionary.
        if unknown_valid:
            await conn.execute(text(
                "UPDATE submissions SET status='needs_species', updated_at=NOW() "
                "WHERE id::text = ANY(:ids)"
            ), {"ids": unknown_valid})
        # No box drawn → the annotator saw no weed → it's a scouting photo, out of the pool.
        # Guard on in_labeling so an idempotent re-run can't reclassify already-final rows.
        scouted = 0
        if zero_box_sids:
            res = await conn.execute(text(
                "UPDATE submissions SET category='scouting', status='stored', updated_at=NOW() "
                "WHERE id::text = ANY(:ids) AND status = 'in_labeling'"
            ), {"ids": zero_box_sids})
            scouted = res.rowcount

    print(f"Imported {total_boxes} label(s) for {len(labeled_valid)} submission(s); "
          f"flipped to status=labeled.", file=sys.stderr)
    if unknown_valid:
        print(f"Note: {len(unknown_valid)} image(s) marked «unknown» → status=needs_species; "
              f"admins pinged to add the species.", file=sys.stderr)
    if scouted:
        print(f"Note: {scouted} image(s) had no box → reclassified to scouting (out of the "
              f"annotation pool).", file=sys.stderr)
    if unknown_valid:
        try:
            await _notify_unknown_weeds(unknown_valid)
        except Exception as exc:
            print(f"notify unknown weeds failed: {exc}", file=sys.stderr)
    if thank_rows:
        try:
            await _thank_uploaders(thank_rows)
        except Exception as exc:
            print(f"thank uploaders failed: {exc}", file=sys.stderr)
    return 0


def _tg_send(chat_id: int, msg: str) -> None:
    """Direct Telegram sendMessage to one chat (through the relay if set)."""
    if not settings.bot_token:
        return
    base = (settings.telegram_api_base or "https://api.telegram.org").rstrip("/")
    requests.post(f"{base}/bot{settings.bot_token}/sendMessage",
                  json={"chat_id": chat_id, "text": msg}, timeout=20)


def _tg_send_photo(chat_id: int, photo_url: str, caption: str) -> None:
    """Telegram sendPhoto by URL (Telegram fetches it) — for the unknown-weed alert so the
    admin sees the actual plant. Falls back to a text message with the link on failure."""
    if not settings.bot_token:
        return
    base = (settings.telegram_api_base or "https://api.telegram.org").rstrip("/")
    r = requests.post(f"{base}/bot{settings.bot_token}/sendPhoto",
                      json={"chat_id": chat_id, "photo": photo_url, "caption": caption}, timeout=30)
    if not r.ok:
        _tg_send(chat_id, f"{caption}\nФото: {photo_url}")


async def _notify_unknown_weeds(sids) -> None:
    """Ping the admins to identify + add a weed the annotator marked «unknown» (not in the
    dictionary). One message per photo, with the image and field/uploader context."""
    from bot.storage import presigned_get
    admins = settings.admin_ids
    if not admins:
        print("notify unknown weeds: no ADMIN_TG_IDS configured.", file=sys.stderr)
        return
    async with engine.connect() as conn:
        rows = (await conn.execute(text(
            "SELECT s.id::text AS id, s.image_url, COALESCE(f.name,'вне пилота') AS field, "
            "       u.full_name AS who "
            "FROM submissions s LEFT JOIN fields f ON f.id = s.field_id "
            "LEFT JOIN users u ON u.id = s.user_id WHERE s.id::text = ANY(:ids)"
        ), {"ids": list(sids)})).mappings().all()
    for r in rows:
        try:
            link = presigned_get(r["image_url"], expires=7 * 24 * 3600)
        except Exception:
            link = None
        cap = ("❓ Неизвестный сорняк — его нет в словаре разметки.\n"
               f"Поле: {r['field']} · прислал: {r['who'] or '—'}\n"
               "Определите вид и добавьте класс командой  /addweed <код_вида>  "
               "(например /addweed cirsium_arvense) — после этого его можно будет размечать.")
        for a in admins:
            try:
                if link:
                    _tg_send_photo(a, link, cap)
                else:
                    _tg_send(a, cap)
            except Exception as exc:
                print(f"notify unknown weed to {a} failed: {exc}", file=sys.stderr)


async def _thank_uploaders(rows) -> None:
    """Tell each agronomist their photo(s) were annotated and now train the AI — push
    + Telegram, best-effort, one grouped message per person. Recognition, not points."""
    by_tg = defaultdict(list)
    for r in rows:
        by_tg[r["tg"]].append((r.get("sub") or "").strip())
    for tg, subs in by_tg.items():
        if len(subs) == 1:
            what = f" «{subs[0]}»" if subs[0] else ""
            msg = (f"🎓 Ваше фото{what} прошло разметку и теперь обучает ИИ Flagleaf. "
                   f"Спасибо за вклад!")
        else:
            msg = (f"🎓 {len(subs)} ваших фото прошли разметку и теперь обучают ИИ Flagleaf. "
                   f"Спасибо за вклад!")
        try:
            await send_push(tg, "Фото обучает ИИ 🎓", msg)
        except Exception as exc:
            print(f"thank: push to {tg} failed: {exc}", file=sys.stderr)
        try:
            _tg_send(tg, msg)
        except Exception as exc:
            print(f"thank: tg to {tg} failed: {exc}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--task", type=int, default=None,
        help="CVAT task ID to fetch annotations from. If set, the export is "
             "requested and downloaded directly from CVAT via the API "
             "(no zip needed on stdin).",
    )
    parser.add_argument(
        "--auto", action="store_true",
        help="Discover every CVAT task marked 'completed' in the project and "
             "import any whose submissions are still in_labeling. No task ID "
             "needed — this is what the nightly cron runs.",
    )
    args = parser.parse_args()

    if args.auto:
        return asyncio.run(_run_auto())

    if args.task is not None:
        try:
            zip_bytes = _fetch_zip_from_cvat(args.task)
        except Exception as exc:
            print(f"ERROR: fetch from CVAT failed: {exc}", file=sys.stderr)
            return 2
    else:
        zip_bytes = sys.stdin.buffer.read()
        if not zip_bytes:
            print("ERROR: no data on stdin and no --task given.\n"
                  "Either pipe a CVAT 'CVAT for Images 1.1' export zip into the "
                  "command, or pass --task <id> to auto-fetch from CVAT.",
                  file=sys.stderr)
            return 1

    return asyncio.run(_import_zip(zip_bytes))


if __name__ == "__main__":
    sys.exit(main())
