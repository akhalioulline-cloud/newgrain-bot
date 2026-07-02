"""Minimal CVAT admin helper used by the bot. /addweed calls add_label() to register a
new species class in the annotation project when the annotator hit a weed that wasn't in
the dictionary (flagged via the «unknown» label → import.py pings the admins). Kept tiny
and synchronous — callers run it via asyncio.to_thread so the bot loop isn't blocked.
"""
import requests

from bot.config import settings

# High-contrast palette (matches the recolour) — new classes pop against green/brown photos.
_COLORS = ["#FF1493", "#00FFFF", "#FFD700", "#FF00FF", "#1E90FF",
           "#FF7F00", "#9400D3", "#FFFF00", "#DC143C", "#FF69B4"]


def _project_headers(base, headers):
    pr = requests.get(f"{base}/api/projects", headers=headers,
                      params={"search": settings.cvat_project_name}, timeout=30)
    pr.raise_for_status()
    proj = next((p for p in pr.json()["results"] if p["name"] == settings.cvat_project_name), None)
    if proj is None:
        return None, headers
    if proj.get("organization") is not None:
        orgs = requests.get(f"{base}/api/organizations", headers=headers, timeout=30).json()
        slug = next((o["slug"] for o in orgs["results"] if o["id"] == proj["organization"]), None)
        if slug:
            headers["X-Organization"] = slug
    return proj, headers


def add_label(name: str):
    """Add a rectangle label `name` to the CVAT project. Returns (ok: bool, info: str)
    where info is the assigned colour on success or a human-readable reason on failure."""
    if not settings.cvat_api_token:
        return False, "CVAT не настроен (нет токена)."
    base = settings.cvat_host
    headers = {"Authorization": f"Bearer {settings.cvat_api_token}"}
    proj, headers = _project_headers(base, headers)
    if proj is None:
        return False, "Проект CVAT не найден."
    labs = requests.get(f"{base}/api/labels", headers=headers,
                        params={"project_id": proj["id"], "page_size": 300}, timeout=30).json()["results"]
    if any(l["name"].lower() == name.lower() for l in labs):
        return False, f"Класс «{name}» уже есть в словаре."
    color = _COLORS[len(labs) % len(_COLORS)]
    cr = requests.post(f"{base}/api/labels", headers={**headers, "Content-Type": "application/json"},
                       json={"name": name, "color": color, "project_id": proj["id"], "type": "any"},
                       timeout=30)
    if not cr.ok:
        return False, f"CVAT отклонил ({cr.status_code})."
    return True, color
