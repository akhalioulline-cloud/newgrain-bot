"""Render simple outline maps of farm fields with Pillow — no basemap, no
network, so it works reliably from the RU server (immune to the RKN/relay
issues that hit outbound tile fetches).

Two views, both returned as PNG bytes:
- closeup:  the target field filled + its neighbouring outlines, zoomed in.
- overview: every field outlined with the target highlighted, so you can see
            where it sits in the whole farm.

Input is field rows with a GeoJSON `gj` string (Polygon / MultiPolygon, EPSG:4326),
typically from db.get_field_polygons().
"""
import io
import json
import math

from PIL import Image, ImageDraw

GREY = (140, 140, 140, 255)
RED_LINE = (200, 0, 0, 255)
RED_FILL = (220, 40, 40, 90)


def _rings(geojson: str):
    """All exterior+interior rings of a (Multi)Polygon as lists of (lon, lat)."""
    g = json.loads(geojson)
    coords = g.get("coordinates", [])
    out = []
    if g.get("type") == "Polygon":
        out = coords
    elif g.get("type") == "MultiPolygon":
        for poly in coords:
            out.extend(poly)
    return [[(pt[0], pt[1]) for pt in ring] for ring in out if len(ring) >= 2]


def build_polys(rows):
    """Parse db rows ({id, is_pilot, gj}) into drawable polys with bboxes."""
    polys = []
    for r in rows:
        if not r["gj"]:
            continue
        rings = _rings(r["gj"])
        if not rings:
            continue
        xs = [lon for ring in rings for lon, _ in ring]
        ys = [lat for ring in rings for _, lat in ring]
        polys.append({
            "id": r["id"],
            "rings": rings,
            "bbox": (min(xs), min(ys), max(xs), max(ys)),
        })
    return polys


def _union_bbox(polys):
    xs0 = [p["bbox"][0] for p in polys]; ys0 = [p["bbox"][1] for p in polys]
    xs1 = [p["bbox"][2] for p in polys]; ys1 = [p["bbox"][3] for p in polys]
    return (min(xs0), min(ys0), max(xs1), max(ys1))


def _intersects(a, b):
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])


def _projector(bbox, size, pad):
    minlon, minlat, maxlon, maxlat = bbox
    coslat = math.cos(math.radians((minlat + maxlat) / 2)) or 1.0
    w, h = size
    dx = max((maxlon - minlon) * coslat, 1e-9)
    dy = max((maxlat - minlat), 1e-9)
    scale = min((w - 2 * pad) / dx, (h - 2 * pad) / dy)
    ox = (w - dx * scale) / 2
    oy = (h - dy * scale) / 2

    def proj(lon, lat):
        return (ox + (lon - minlon) * coslat * scale, oy + (maxlat - lat) * scale)

    return proj


def _draw(polys, target_id, bbox, size=(1000, 1000), pad=30):
    img = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(img, "RGBA")
    proj = _projector(bbox, size, pad)
    target = None
    for p in polys:
        if p["id"] == target_id:
            target = p
            continue
        for ring in p["rings"]:
            pts = [proj(lon, lat) for lon, lat in ring]
            if len(pts) >= 2:
                d.line(pts + [pts[0]], fill=GREY, width=1)
    if target:
        for ring in target["rings"]:
            pts = [proj(lon, lat) for lon, lat in ring]
            if len(pts) >= 3:
                d.polygon(pts, fill=RED_FILL)
                d.line(pts + [pts[0]], fill=RED_LINE, width=3)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def render_overview(polys, target_id):
    """All fields, target highlighted — where it sits in the whole farm."""
    return _draw(polys, target_id, _union_bbox(polys))


def render_closeup(polys, target_id):
    """The target field + its neighbours, zoomed to the field's surroundings."""
    target = next((p for p in polys if p["id"] == target_id), None)
    if target is None:
        return None
    minlon, minlat, maxlon, maxlat = target["bbox"]
    m = max(maxlon - minlon, maxlat - minlat) * 0.6 or 0.001
    view = (minlon - m, minlat - m, maxlon + m, maxlat + m)
    near = [p for p in polys if _intersects(p["bbox"], view)]
    return _draw(near, target_id, view)
