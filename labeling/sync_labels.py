"""Sync labeling/cvat_labels.json into the live CVAT Cloud project (idempotent).

Adds any label that's in the JSON but missing from the project. It NEVER
deletes or edits existing labels — only new ones (sent without an id) are
created — so annotations already in progress are safe.

    # see the diff without changing anything
    ssh newgrain@158.160.46.89 \\
        'cd newgrain-bot && docker compose -f docker-compose.prod.yml run --rm bot \\
         python -m labeling.sync_labels --dry-run'

    # apply (add the missing labels)
    ssh newgrain@158.160.46.89 \\
        'cd newgrain-bot && docker compose -f docker-compose.prod.yml run --rm bot \\
         python -m labeling.sync_labels'

Run it whenever cvat_labels.json changes (e.g. a new weed class is promoted).
"""
import argparse
import json
import sys
from pathlib import Path

import requests

from bot.config import settings

LABELS_FILE = Path(__file__).with_name("cvat_labels.json")


def _headers():
    if not settings.cvat_api_token:
        raise RuntimeError(
            "CVAT_API_TOKEN not set in .env. Generate one at "
            f"{settings.cvat_host}/auth/settings (Settings → Personal access tokens)."
        )
    # Bearer scheme (CVAT Cloud-specific; verified in export.py/import.py).
    return {"Authorization": f"Bearer {settings.cvat_api_token}"}


def _resolve_project(base, headers):
    r = requests.get(f"{base}/api/projects", headers=headers,
                     params={"search": settings.cvat_project_name}, timeout=30)
    r.raise_for_status()
    project = next((p for p in r.json()["results"]
                    if p["name"] == settings.cvat_project_name), None)
    if project is None:
        raise RuntimeError(f"CVAT project {settings.cvat_project_name!r} not found.")
    org_id = project.get("organization")
    if org_id is not None:
        orgs = requests.get(f"{base}/api/organizations", headers=headers, timeout=30).json()
        slug = next((o["slug"] for o in orgs["results"] if o["id"] == org_id), None)
        if slug:
            headers["X-Organization"] = slug
    return project["id"]


def _project_label_names(base, headers, project_id):
    names, url, params = [], f"{base}/api/labels", {"project_id": project_id, "page_size": 100}
    while url:
        r = requests.get(url, headers=headers, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        names += [lbl["name"] for lbl in data.get("results", [])]
        url, params = data.get("next"), None
    return names


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true",
                    help="Only report what would be added; don't modify CVAT.")
    args = ap.parse_args()

    desired = json.loads(LABELS_FILE.read_text(encoding="utf-8"))
    base, headers = settings.cvat_host, _headers()
    project_id = _resolve_project(base, headers)
    have = set(_project_label_names(base, headers, project_id))
    missing = [lbl for lbl in desired if lbl["name"] not in have]

    print(f"CVAT project #{project_id} ({settings.cvat_project_name!r}): "
          f"{len(have)} labels present, {len(desired)} in JSON, "
          f"{len(missing)} to add.", file=sys.stderr)
    for lbl in missing:
        print(f"  + {lbl['name']} ({lbl['type']})", file=sys.stderr)

    if not missing:
        print("Already in sync — nothing to do.", file=sys.stderr)
        return 0
    if args.dry_run:
        print("--dry-run: CVAT not modified.", file=sys.stderr)
        return 0

    # PATCH with labels that have NO id → CVAT creates them. Existing labels are
    # absent from the payload, so they are left untouched (not deleted).
    payload = {"labels": [
        {"name": lbl["name"], "type": lbl["type"],
         "color": lbl.get("color"), "attributes": lbl.get("attributes", [])}
        for lbl in missing
    ]}
    r = requests.patch(f"{base}/api/projects/{project_id}",
                       headers={**headers, "Content-Type": "application/json"},
                       json=payload, timeout=60)
    r.raise_for_status()

    after = set(_project_label_names(base, headers, project_id))
    added, lost = sorted(after - have), sorted(have - after)
    print(f"Added: {added}", file=sys.stderr)
    if lost:
        print(f"⚠️  WARNING: these labels disappeared — investigate: {lost}",
              file=sys.stderr)
        return 2
    print(f"✅ CVAT project now has {len(after)} labels.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
