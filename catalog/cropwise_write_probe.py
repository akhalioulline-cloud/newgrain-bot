"""SAFE one-off probe: does our CROPWISE_OPERATIONS_TOKEN have WRITE permission?

POSTs an EMPTY agro_operation. The API should reject it for validation (creating
nothing). The *kind* of rejection is the answer:
  401/403  -> token is READ-ONLY (writes denied)
  400/422  -> WRITE ALLOWED (only the empty payload was rejected; nothing created)
  200/201  -> WRITE ALLOWED and a record was created -> this probe DELETES it again
  405      -> POST not allowed on /agro_operations

Self-cleaning: if anything is created, it is deleted immediately. Run by the
OWNER (Claude is blocked from external writes):
  docker compose -f docker-compose.prod.yml run --rm -T bot python -m catalog.cropwise_write_probe
"""
import os
import sys

import requests

B = "https://operations.cropwise.com/api/v3"
H = {"X-User-Api-Token": os.environ.get("CROPWISE_OPERATIONS_TOKEN", ""),
     "Content-Type": "application/json"}


def main():
    if not H["X-User-Api-Token"]:
        print("CROPWISE_OPERATIONS_TOKEN not set", file=sys.stderr)
        return 1
    r = requests.post(f"{B}/agro_operations", headers=H, json={"data": {}}, timeout=60)
    print("HTTP", r.status_code)
    print("BODY", r.text[:600])

    cid = None
    try:
        j = r.json()
        if isinstance(j.get("data"), dict):
            cid = j["data"].get("id")
    except Exception:
        pass
    if cid:
        print(f"CREATED id={cid} — deleting to clean up…")
        d = requests.delete(f"{B}/agro_operations/{cid}", headers=H, timeout=60)
        print("CLEANUP DELETE HTTP", d.status_code,
              "(if not 2xx, delete it manually in CropWise)")

    if r.status_code in (401, 403):
        print("VERDICT: READ-ONLY token — writes denied")
    elif r.status_code in (400, 422):
        print("VERDICT: WRITE ALLOWED (validation rejection, nothing created)")
    elif r.status_code in (200, 201):
        print("VERDICT: WRITE ALLOWED (a record was created, then deleted above)")
    elif r.status_code == 405:
        print("VERDICT: POST not allowed on /agro_operations")
    else:
        print("VERDICT: unclear — see BODY above")
    return 0


if __name__ == "__main__":
    sys.exit(main())
