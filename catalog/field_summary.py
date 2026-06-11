"""Field data-layer summary — a first taste of the agent reading the integrated
layer (treatment history + weather + NDVI + pesticide catalog) for one field.

Run: docker compose -f docker-compose.prod.yml run --rm -T bot \
       python -m catalog.field_summary "Поле 76/108"
"""
import argparse
import asyncio
import sys

from sqlalchemy import text

from bot.db import engine


def _catalog_stem(crop):
    t = (crop or "").lower()
    if "пшениц" in t:
        return "пшениц"
    if "подсолнеч" in t:
        return "подсолнеч"
    if "соя" in t or "сои" in t:
        return "соя"
    return t.split()[0] if t else ""


async def summary(field):
    async with engine.connect() as conn:
        f = (await conn.execute(
            text("SELECT id, name, crop, area_ha FROM fields WHERE name=:n"), {"n": field})).first()
        if not f:
            print(f"field '{field}' not found"); return
        fid = f.id
        print(f"════ {f.name}  (паспортная культура: {f.crop or '—'}, {f.area_ha or '?'} га) ════")

        span = (await conn.execute(text(
            "SELECT min(season) a, max(season) b, count(*) c FROM field_treatments WHERE field_id=:i"),
            {"i": fid})).first()
        cats = (await conn.execute(text(
            "SELECT op_category, count(*) c FROM field_treatments WHERE field_id=:i "
            "GROUP BY op_category ORDER BY c DESC"), {"i": fid})).all()
        print(f"\n■ Operations: {span.c} across seasons {span.a}–{span.b}  "
              + ", ".join(f"{c.op_category}={c.c}" for c in cats))
        recent = (await conn.execute(text(
            "SELECT treatment_date d, crop, product, dose FROM field_treatments "
            "WHERE field_id=:i AND op_category='protection' ORDER BY treatment_date DESC LIMIT 6"),
            {"i": fid})).all()
        print("  recent plant-protection:")
        for r in recent:
            print(f"    {r.d}  {r.crop or '—'}: {r.product} @ {r.dose or '—'}")

        w = (await conn.execute(text(
            "SELECT source, count(*) c, min(date) a, max(date) b FROM weather_daily "
            "WHERE field_id=:i GROUP BY source ORDER BY source"), {"i": fid})).all()
        print("\n■ Weather:")
        for x in w:
            print(f"    {x.source}: {x.c} days ({x.a} … {x.b})")
        if not w:
            print("    (none)")

        v = (await conn.execute(text(
            "SELECT count(*) weeks, count(ndvi) ndvi_n, max(week_start) latest "
            "FROM vegetation_weekly WHERE field_id=:i"), {"i": fid})).first()
        print(f"\n■ Vegetation: {v.weeks} weeks, {v.ndvi_n} with NDVI (latest {v.latest})")
        ndvi = (await conn.execute(text(
            "SELECT week_start w, round(ndvi,2) nd FROM vegetation_weekly "
            "WHERE field_id=:i AND ndvi IS NOT NULL ORDER BY week_start DESC LIMIT 6"), {"i": fid})).all()
        if ndvi:
            print("    recent NDVI: " + ", ".join(f"{r.w}={r.nd}" for r in reversed(ndvi)))

        cur = (await conn.execute(text(
            "SELECT crop FROM field_treatments WHERE field_id=:i AND crop IS NOT NULL AND crop<>'' "
            "ORDER BY treatment_date DESC LIMIT 1"), {"i": fid})).scalar()
        stem = _catalog_stem(cur)
        if stem:
            n = (await conn.execute(text(
                "SELECT count(*) FROM pesticide_applications WHERE lower(crop) LIKE :s AND status='Действует'"),
                {"s": f"%{stem}%"})).scalar()
            print(f"\n■ Catalog: ~{n} active registered products applicable to current crop "
                  f"'{cur}' — the agent's recommendation candidate set.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("field")
    args = ap.parse_args()
    asyncio.run(summary(args.field))
    return 0


if __name__ == "__main__":
    sys.exit(main())
