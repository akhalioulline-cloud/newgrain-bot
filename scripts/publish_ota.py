#!/usr/bin/env python3
"""Publish an over-the-air update to OUR server (ai.flagleaf.ru) — replaces `eas update`
after Expo's CDN silently 403'd our assets (8 Jul 2026; see backlog).

Flow: expo export → per-platform Expo-Updates-protocol manifest (deterministic update id =
uuid5 of content hashes, so re-publishing identical content is a no-op for clients) → rsync
the whole dist to the VM's static dir. The API serves /api/ota/manifest (multipart, with
noUpdateAvailable directive when the client is current); nginx serves the assets statically.

Run from repo root:  python3 scripts/publish_ota.py "message describing the update"
"""
import base64
import hashlib
import json
import mimetypes
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MOBILE = REPO / "mobile"
DIST = MOBILE / "dist-ota"
ASSET_BASE = "https://ai.flagleaf.ru/updates/dist"
VM = "newgrain@111.88.248.159"
VM_DIR = "/var/www/ai/updates/dist"
SSH_KEY = str(Path.home() / ".ssh" / "id_ed25519")
NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")  # uuid5 namespace (DNS ns, arbitrary but fixed)


def sha256_b64url(p: Path) -> str:
    h = hashlib.sha256(p.read_bytes()).digest()
    return base64.urlsafe_b64encode(h).decode().rstrip("=")


def asset_entry(rel: str, ext: str | None) -> dict:
    p = DIST / rel
    ctype = mimetypes.guess_type(f"x.{ext}")[0] if ext else "application/octet-stream"
    e = {
        "hash": sha256_b64url(p),
        "key": p.name.split(".")[0],
        "contentType": ctype or "application/octet-stream",
        "url": f"{ASSET_BASE}/{rel}",
    }
    if ext:
        e["fileExtension"] = f".{ext}"
    return e


def main() -> None:
    message = sys.argv[1] if len(sys.argv) > 1 else "update"
    version = json.loads((MOBILE / "app.json").read_text())["expo"]["version"]

    print("→ expo export (android + ios)…")
    subprocess.run(["npx", "expo", "export", "--platform", "all", "--output-dir", "dist-ota"],
                   cwd=MOBILE, check=True, capture_output=True)

    meta = json.loads((DIST / "metadata.json").read_text())
    for platform, fm in meta["fileMetadata"].items():
        launch = asset_entry(fm["bundle"], None)
        launch["contentType"] = "application/javascript"
        assets = [asset_entry(a["path"], a["ext"]) for a in fm["assets"]]
        content_sig = hashlib.sha256(
            (platform + version + launch["hash"] + "".join(sorted(a["hash"] for a in assets))).encode()
        ).hexdigest()
        manifest = {
            "id": str(uuid.uuid5(NS, content_sig)),
            "createdAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "runtimeVersion": version,
            "launchAsset": launch,
            "assets": assets,
            "metadata": {},
            "extra": {"message": message},
        }
        (DIST / f"manifest-{platform}.json").write_text(json.dumps(manifest))
        print(f"  {platform}: update id {manifest['id']}  (runtime {version})")

    print("→ uploading to ai.flagleaf.ru…")
    subprocess.run(["ssh", "-i", SSH_KEY, VM, f"mkdir -p {VM_DIR}"], check=True)
    subprocess.run(["rsync", "-az", "-e", f"ssh -i {SSH_KEY}", f"{DIST}/", f"{VM}:{VM_DIR}/"], check=True)
    print(f"✔ published: “{message}” — clients pick it up on next app launch")


if __name__ == "__main__":
    main()
