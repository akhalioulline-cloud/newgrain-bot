"""CropWise Open Platform — discovery probe (read-only).

Run this ONCE Syngenta grants OAuth credentials, to discover the real API shapes
(orgs → properties → fields → agro-operations, and remote-sensing/NDVI) before we
build the full sync. It authenticates (client-credentials), then lists the
hierarchy and dumps a sample operation so we can map fields to our schema.

Set in the server .env (values from Syngenta):
  CROPWISE_TOKEN_URL=...      # OAuth2 token endpoint
  CROPWISE_CLIENT_ID=...
  CROPWISE_CLIENT_SECRET=...
  CROPWISE_BASE_URL=...       # e.g. https://api.base.cropwise.com
  CROPWISE_SCOPE=...          # optional

Run: docker compose -f docker-compose.prod.yml run --rm -T \
       -e CROPWISE_TOKEN_URL -e CROPWISE_CLIENT_ID -e CROPWISE_CLIENT_SECRET \
       -e CROPWISE_BASE_URL -e CROPWISE_SCOPE \
       bot python -m catalog.cropwise_probe
"""
import json
import os
import sys

import requests

TOKEN_URL = os.environ.get("CROPWISE_TOKEN_URL", "")
CLIENT_ID = os.environ.get("CROPWISE_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("CROPWISE_CLIENT_SECRET", "")
BASE = os.environ.get("CROPWISE_BASE_URL", "https://api.base.cropwise.com").rstrip("/")
SCOPE = os.environ.get("CROPWISE_SCOPE", "")


def _get_token():
    data = {"grant_type": "client_credentials"}
    if SCOPE:
        data["scope"] = SCOPE
    # try HTTP Basic first, then client creds in body
    for kw in ({"auth": (CLIENT_ID, CLIENT_SECRET)},
               {"data": {**data, "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET}}):
        try:
            r = requests.post(TOKEN_URL, data=data if "auth" in kw else None, timeout=30, **kw)
            if r.ok and "access_token" in r.json():
                print(f"  token OK via {'basic' if 'auth' in kw else 'body'} auth", file=sys.stderr)
                return r.json()["access_token"]
            print(f"  token attempt -> {r.status_code}: {r.text[:200]}", file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            print(f"  token attempt error: {e}", file=sys.stderr)
    return None


def _get(token, path, headers=None):
    url = path if path.startswith("http") else f"{BASE}{path}"
    h = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    h.update(headers or {})
    r = requests.get(url, headers=h, timeout=30)
    return r.status_code, (r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text)


def _show(label, code, body):
    print(f"\n=== {label} -> HTTP {code} ===")
    s = json.dumps(body, ensure_ascii=False, indent=2) if isinstance(body, (dict, list)) else str(body)
    print(s[:1500])


def main():
    if not (TOKEN_URL and CLIENT_ID and CLIENT_SECRET):
        print("Missing CROPWISE_TOKEN_URL / CLIENT_ID / CLIENT_SECRET in env.", file=sys.stderr)
        return 1
    print(f"base={BASE}", file=sys.stderr)
    token = _get_token()
    if not token:
        print("Could not obtain a token — check creds/token URL/flow.", file=sys.stderr)
        return 1

    # documented Core Services paths (v2); we probe and report what works
    for label, path in [("orgs", "/v2/orgs"), ("properties", "/v2/properties"), ("fields", "/v2/fields")]:
        try:
            code, body = _get(token, path)
            _show(label, code, body)
        except Exception as e:  # noqa: BLE001
            print(f"{label}: error {e}", file=sys.stderr)
    print("\n--- Next: identify the agro-operations + remote-sensing(NDVI) paths from the "
          "above hierarchy (org/property/field ids) and re-probe. ---", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
