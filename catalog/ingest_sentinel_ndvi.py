"""Fresh per-field NDVI from Sentinel-2, straight from the AWS open mirror.

Fewest intermediaries: STAC search (earth-search) → read red(B04)+nir(B08)+SCL
COGs directly from the sentinel-cogs S3 over https (windowed, per field polygon)
→ cloud-mask via SCL → mean NDVI per field → upsert vegetation_weekly
(source='sentinel'), and drop the static cropwise_bulk value for that field+week
so the reader sees one NDVI per week. No Sentinel Hub, no SDK, no API key.

Copernicus direct is blocked from the RU VM; the AWS mirror is reachable.

Run (weekly cron, all fields with geometry):
    python -m catalog.ingest_sentinel_ndvi
Test one field without writing:
    python -m catalog.ingest_sentinel_ndvi --field 142 --dry
"""
import argparse
import asyncio
import os
import sys
from datetime import date, datetime, timedelta, timezone

import requests

os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif")
os.environ.setdefault("GDAL_HTTP_MULTIPLEX", "YES")
os.environ.setdefault("VSI_CACHE", "TRUE")
os.environ.setdefault("AWS_NO_SIGN_REQUEST", "YES")

import numpy as np  # noqa: E402  (after env so GDAL picks it up cleanly)
import rasterio  # noqa: E402
from rasterio.mask import mask as rio_mask  # noqa: E402
from rasterio.warp import transform_geom  # noqa: E402
from sqlalchemy import text  # noqa: E402

from bot.db import engine  # noqa: E402

STAC = "https://earth-search.aws.element84.com/v1/search"
COLLECTION = "sentinel-2-l2a"
# SCL classes to KEEP: 4 vegetation, 5 bare soil. Everything else (0 nodata,
# 1 saturated, 2 dark, 3 cloud shadow, 6 water, 7 unclassified, 8/9/10 cloud,
# 11 snow) is dropped so clouds/shadows don't poison the field mean.
KEEP_SCL = {4, 5}
# The earth-search / sentinel-cogs COGs store reflectance directly as DN/10000
# (NO +1000 baseline offset — verified empirically: red DN ~370, and applying a
# -1000 offset drove reflectance negative, NDVI ~ -0.4; no offset → NDVI ~0.47,
# matching CropWise). NDVI is scale-invariant anyway, so DN_SCALE is cosmetic.
DN_OFFSET, DN_SCALE = 0.0, 10000.0


def _bbox_intersects(a, b):
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])


def _search_scenes(bbox, days):
    """Recent Sentinel-2 L2A scenes intersecting the farm bbox, newest first."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    payload = {
        "collections": [COLLECTION],
        "bbox": bbox,
        "datetime": f"{start:%Y-%m-%dT%H:%M:%SZ}/{end:%Y-%m-%dT%H:%M:%SZ}",
        "query": {"eo:cloud_cover": {"lt": 90}},
        "limit": 100,
    }
    r = requests.post(STAC, json=payload, timeout=60)
    r.raise_for_status()
    feats = r.json().get("features", [])
    feats.sort(key=lambda f: f["properties"]["datetime"], reverse=True)
    return feats


def _asset(feat, *names):
    for n in names:
        a = feat.get("assets", {}).get(n)
        if a and a.get("href"):
            return a["href"]
    return None


def _field_ndvi(geom4326, fbbox, scenes, max_try=4):
    """Try recent scenes (newest first) until one yields enough clear pixels over
    the field; return (ndvi, scene_date) or (None, None)."""
    tried = 0
    for feat in scenes:
        if not _bbox_intersects(fbbox, feat.get("bbox", [-180, -90, 180, 90])):
            continue
        red_h = _asset(feat, "red", "B04")
        nir_h = _asset(feat, "nir", "B08")
        scl_h = _asset(feat, "scl", "SCL")
        if not (red_h and nir_h and scl_h):
            continue
        tried += 1
        try:
            with rasterio.open(red_h) as ds:
                g = transform_geom("EPSG:4326", ds.crs, geom4326)
                red, _ = rio_mask(ds, [g], crop=True, filled=True, nodata=0)
            with rasterio.open(nir_h) as ds:
                g = transform_geom("EPSG:4326", ds.crs, geom4326)
                nir, _ = rio_mask(ds, [g], crop=True, filled=True, nodata=0)
            with rasterio.open(scl_h) as ds:
                g = transform_geom("EPSG:4326", ds.crs, geom4326)
                scl, _ = rio_mask(ds, [g], crop=True, filled=True, nodata=0)
        except Exception as exc:
            print(f"   scene read failed: {exc}", file=sys.stderr)
            if tried >= max_try:
                break
            continue
        red = red[0].astype("float32"); nir = nir[0].astype("float32")
        scl = scl[0]
        # SCL is 20 m vs 10 m red/nir → upsample 2× and crop to red's shape.
        scl_up = np.repeat(np.repeat(scl, 2, axis=0), 2, axis=1)
        scl_up = scl_up[: red.shape[0], : red.shape[1]]
        if scl_up.shape != red.shape:  # ragged edge — pad
            sh = np.zeros_like(red, dtype=scl_up.dtype)
            sh[: scl_up.shape[0], : scl_up.shape[1]] = scl_up
            scl_up = sh
        # L2A surface reflectance, clipped to a sane range.
        r_refl = np.clip((red - DN_OFFSET) / DN_SCALE, 0.0, 1.5)
        n_refl = np.clip((nir - DN_OFFSET) / DN_SCALE, 0.0, 1.5)
        # Keep clear land pixels with real reflectance — the >0.1 sum drops
        # near-zero-denominator pixels (shadow/edge) that would explode the ratio.
        keep = (np.isin(scl_up, list(KEEP_SCL)) & (red > 0) & (nir > 0)
                & ((n_refl + r_refl) > 0.1))
        field_px = int((red > 0).sum()) or 1
        if keep.sum() < max(10, 0.20 * field_px):
            if tried >= max_try:
                break
            continue  # too cloudy over this field — older scene
        denom = n_refl[keep] + r_refl[keep]
        ndvi_px = np.clip((n_refl[keep] - r_refl[keep]) / denom, -1.0, 1.0)
        ndvi = float(np.mean(ndvi_px))
        sdate = datetime.fromisoformat(
            feat["properties"]["datetime"].replace("Z", "+00:00")).date()
        return round(ndvi, 3), sdate
    return None, None


async def run(only_field, dry, days):
    async with engine.connect() as conn:
        sql = ("SELECT id, name, ST_AsGeoJSON(geom) gj, "
               "ST_XMin(geom) x0, ST_YMin(geom) y0, ST_XMax(geom) x1, ST_YMax(geom) y1 "
               "FROM fields WHERE geom IS NOT NULL")
        params = {}
        if only_field:
            sql += " AND id = :id"; params["id"] = only_field
        rows = (await conn.execute(text(sql), params)).mappings().all()
        farm = (await conn.execute(text(
            "SELECT ST_XMin(e), ST_YMin(e), ST_XMax(e), ST_YMax(e) FROM "
            "(SELECT ST_Extent(geom) e FROM fields WHERE geom IS NOT NULL) s"))).first()
    if not rows:
        print("no fields with geometry.", file=sys.stderr); return 1
    bbox = [float(farm[0]), float(farm[1]), float(farm[2]), float(farm[3])]
    print(f"searching Sentinel-2 over farm bbox, last {days} days…", file=sys.stderr)
    import json
    scenes = _search_scenes(bbox, days)
    print(f"  {len(scenes)} scene(s) found.", file=sys.stderr)
    if not scenes:
        return 1

    rasterio_env = rasterio.Env(GDAL_HTTP_MULTIPLEX="YES")
    done = miss = 0
    with rasterio_env:
        for r in rows:
            geom = json.loads(r["gj"])
            fbbox = [float(r["x0"]), float(r["y0"]), float(r["x1"]), float(r["y1"])]
            ndvi, sdate = _field_ndvi(geom, fbbox, scenes)
            if ndvi is None:
                miss += 1
                print(f"  {r['name']}: no clear scene", file=sys.stderr); continue
            done += 1
            ws = sdate - timedelta(days=sdate.weekday())
            wn = sdate.isocalendar()[1]
            print(f"  {r['name']}: NDVI {ndvi} ({sdate}, week {wn})", file=sys.stderr)
            if dry:
                continue
            async with engine.begin() as conn:
                await conn.execute(text(
                    "INSERT INTO vegetation_weekly (field_id, week_start, week_no, ndvi, source) "
                    "VALUES (:i,:ws,:wn,:nd,'sentinel') "
                    "ON CONFLICT (field_id, week_start, source) "
                    "DO UPDATE SET ndvi=EXCLUDED.ndvi, week_no=EXCLUDED.week_no"),
                    {"i": r["id"], "ws": ws, "wn": wn, "nd": ndvi})
                # one NDVI per field+week: drop the static bulk value Sentinel now covers
                await conn.execute(text(
                    "DELETE FROM vegetation_weekly WHERE source='cropwise_bulk' "
                    "AND field_id=:i AND week_start=:ws"), {"i": r["id"], "ws": ws})
    verb = "computed" if dry else "updated"
    print(f"done: {done} field(s) {verb}, {miss} without a clear scene.", file=sys.stderr)
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--field", type=int, default=None, help="single field id (test)")
    ap.add_argument("--days", type=int, default=20, help="lookback window")
    ap.add_argument("--dry", action="store_true", help="compute + print, no DB write")
    args = ap.parse_args()
    return asyncio.run(run(args.field, args.dry, args.days))


if __name__ == "__main__":
    sys.exit(main())
