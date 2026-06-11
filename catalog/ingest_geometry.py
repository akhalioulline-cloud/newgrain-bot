"""Ingest field boundaries from the CropWise GeoJSON export (АОНЗК.json) into
fields.geom (PostGIS), and set fields.cropwise_id from the feature id.

Matches each feature to a field by its "Имя" (GeoJSON properties.name) recovered
from our field name. MultiPolygon, WGS84 (SRID 4326).

Run: docker compose -f docker-compose.prod.yml run --rm -T -v /tmp/fields.json:/data.json \
       bot python -m catalog.ingest_geometry /data.json
"""
import argparse
import asyncio
import json
import re
import sys

from sqlalchemy import text

from bot.db import engine


def _ima(name):
    if " · " in name:
        return name.split(" · ")[0].replace("Поле ", "").strip()
    m = re.match(r"Поле\s+(\d+)", name or "")
    return m.group(1) if m else (name or "").strip()


async def run(path):
    data = json.load(open(path, encoding="utf-8"))
    feats = data.get("features", []) if isinstance(data, dict) else []
    async with engine.begin() as conn:
        fields = (await conn.execute(text("SELECT id, name FROM fields"))).all()
        ima2id = {}
        for fid, nm in fields:
            ima2id.setdefault(_ima(nm), fid)

        matched, unmatched = 0, []
        for f in feats:
            props = f.get("properties", {})
            ima = str(props.get("name", "")).strip()
            fid = ima2id.get(ima)
            if not fid:
                unmatched.append(ima)
                continue
            cwid = f.get("id")
            try:
                cwid = int(cwid)
            except (TypeError, ValueError):
                cwid = None
            await conn.execute(text(
                "UPDATE fields SET geom = ST_SetSRID(ST_Multi(ST_GeomFromGeoJSON(:g)), 4326), "
                "cropwise_id = COALESCE(:c, cropwise_id) WHERE id = :i"),
                {"g": json.dumps(f["geometry"]), "c": cwid, "i": fid})
            matched += 1

    print(f"geometries set: {matched} | unmatched features: {len(unmatched)} "
          f"({', '.join(unmatched[:12])}{'…' if len(unmatched) > 12 else ''})", file=sys.stderr)
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("geojson")
    args = ap.parse_args()
    return asyncio.run(run(args.geojson))


if __name__ == "__main__":
    sys.exit(main())
