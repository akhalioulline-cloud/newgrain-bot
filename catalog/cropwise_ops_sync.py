"""Sync the whole farm's field operations from the Cropwise Operations API (v3)
into field_treatments (source='cropwise_api') — the live replacement for the
hand-imported multiprotocols. Auth: CROPWISE_OPERATIONS_TOKEN via X-User-Api-Token
(the operations.cropwise.com 'linked devices' token).

Each agro_operation → one field_treatments row per product in its
application_mix_items (Chemical→protection, Fertilizer→fertilizer, Seed→sowing);
operations with no mix (tillage/harvest) → one row, product NULL. Idempotent via
the natural-key index. After a successful sync it RETIRES the manual import rows
for any field the API now covers (API is the source of truth). Active substances
are filled by the existing enrich step afterwards.

  python -m catalog.cropwise_ops_sync --dry [--field 119]   # preview, no writes
  python -m catalog.cropwise_ops_sync                        # sync + retire manual
"""
import argparse
import asyncio
import os
import re
import sys
from datetime import date, datetime

import requests
from sqlalchemy import text

from bot.db import engine

BASE = "https://operations.cropwise.com/api/v3"
HEADERS = {"X-User-Api-Token": os.environ.get("CROPWISE_OPERATIONS_TOKEN", "")}
TYPE_CAT = {"Chemical": "protection", "Fertilizer": "fertilizer", "Seed": "sowing"}


def _get(path, **params):
    r = requests.get(f"{BASE}/{path}", headers=HEADERS, params=params, timeout=90)
    r.raise_for_status()
    return r.json()


def _all(path, **params):
    """All rows of a v3 resource via id-based pagination (from_id exclusive)."""
    out, from_id = [], 0
    while True:
        rows = _get(path, from_id=from_id, per_page=1000, **params).get("data", [])
        if not rows:
            break
        out.extend(rows)
        if len(rows) < 1000:
            break
        from_id = max(r["id"] for r in rows)
    return out


def _norm(s):
    return (s or "").strip().lower().replace("ё", "е")


def _lead_int(name):
    m = re.match(r"\D*(\d+)", name or "")
    return int(m.group(1)) if m else None


def _worktype_cat(name):
    n = (name or "").lower()
    if any(k in n for k in ("опрыск", "сзр", "защит", "гербицид", "фунгицид", "инсектицид")):
        return "protection"
    if any(k in n for k in ("удобр", "внесен", "подкорм")):
        return "fertilizer"
    if any(k in n for k in ("сев", "посев", "посадк")):
        return "sowing"
    if any(k in n for k in ("обработка почв", "культив", "боронов", "дисков", "лущен",
                            "вспаш", "глубокорыхл", "рыхлен", "прикатыв", "subsoil", "disc")):
        return "tillage"
    if any(k in n for k in ("уборк", "урожай", "harvest")):
        return "harvest"
    return "other"


def _parse_date(s):
    if not s:
        return None
    try:
        return date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


async def build_rows(only_field=None):
    """Fetch the API + map operations to field_treatments row dicts. Returns
    (rows, stats)."""
    print("fetching dictionaries…", file=sys.stderr)
    api_fields = {f["id"]: f for f in _all("fields")}
    groups = {g["id"]: g["name"] for g in _all("field_groups")}
    worktypes = {w["id"]: w["name"] for w in _all("work_types")}
    prod_dict = {
        "Chemical": {c["id"]: c["name"] for c in _all("chemicals")},
        "Fertilizer": {f["id"]: f["name"] for f in _all("fertilizers")},
        "Seed": {s["id"]: s["name"] for s in _all("seeds")},
    }
    print(f"  fields={len(api_fields)} chemicals={len(prod_dict['Chemical'])} "
          f"fertilizers={len(prod_dict['Fertilizer'])} seeds={len(prod_dict['Seed'])}",
          file=sys.stderr)

    async with engine.connect() as conn:
        ours = (await conn.execute(text("SELECT id, name, area_ha FROM fields"))).all()
        fcrops = (await conn.execute(text(
            "SELECT field_id, year, crop FROM field_crops WHERE crop IS NOT NULL"))).all()
    by_name = {_norm(n): i for i, n, _a in ours}
    by_numarea = {}
    for i, n, a in ours:
        li = _lead_int(n)
        if li is not None and a is not None:
            by_numarea[(li, round(float(a)))] = i
    crop_map = {(fid, yr): crop for fid, yr, crop in fcrops}

    def map_field(af):
        num = str(af.get("name", "")).strip()
        grp = groups.get(af.get("field_group_id"), "")
        target = f"Поле {num} · {grp}" if grp else f"Поле {num}"
        fid = by_name.get(_norm(target))
        if fid:
            return fid, target
        area = af.get("area") or af.get("calculated_area") or af.get("cadastral_area")
        if area:
            fid = by_numarea.get((_lead_int(num), round(float(area))))
        return fid, target

    print("fetching agro_operations…", file=sys.stderr)
    ops = _all("agro_operations")
    print(f"  {len(ops)} operations", file=sys.stderr)

    rows, unmatched = [], set()
    cat_counts = {}
    for op in ops:
        af = api_fields.get(op.get("field_id"))
        if not af:
            continue
        fid, fname = map_field(af)
        if not fid:
            unmatched.add(fname)
            continue
        if only_field and str(only_field) not in fname:
            continue
        td = _parse_date(op.get("completed_date") or op.get("planned_start_date"))
        if not td:
            continue
        season = op.get("season") or td.year
        area = op.get("completed_area") or op.get("planned_area")
        depth = op.get("planned_depth")
        note = f"глубина {depth}" if depth else None
        wt_name = worktypes.get(op.get("work_type_id")) or op.get("operation_subtype") or "операция"
        crop = crop_map.get((fid, season))
        mix = op.get("application_mix_items") or []
        items = mix if mix else [None]
        for it in items:
            if it is not None:
                t = it.get("applicable_type")
                product = prod_dict.get(t, {}).get(it.get("applicable_id"))
                cat = TYPE_CAT.get(t) or _worktype_cat(wt_name)
                rate = it.get("planned_rate") or it.get("fact_rate")
                unit = it.get("rate_unit_label_per_area") or ""
                dose = f"{rate:g} {unit}".strip() if rate else None
            else:
                product, dose = None, None
                cat = _worktype_cat(wt_name)
            cat_counts[cat] = cat_counts.get(cat, 0) + 1
            rows.append({
                "field_id": fid, "field_name": fname, "treatment_date": td,
                "season": season, "crop": crop, "operation": wt_name,
                "op_category": cat, "product": product, "dose": dose,
                "area_ha": float(area) if area else None, "note": note,
            })
    stats = {"ops": len(ops), "rows": len(rows), "unmatched_fields": sorted(unmatched),
             "by_category": cat_counts}
    return rows, stats


async def run(dry, only_field):
    rows, stats = await build_rows(only_field)
    print(f"\nmapped {stats['rows']} rows from {stats['ops']} operations; "
          f"by category: {stats['by_category']}", file=sys.stderr)
    if stats["unmatched_fields"]:
        print(f"unmatched API fields ({len(stats['unmatched_fields'])}): "
              f"{', '.join(stats['unmatched_fields'][:15])}…", file=sys.stderr)
    if dry:
        for r in rows[:12]:
            print(f"  {r['field_name']} | {r['treatment_date']} | {r['op_category']} | "
                  f"{r['operation']} | {r['product']} | {r['dose']} | {r['area_ha']}")
        print(f"\n[dry-run] would write {len(rows)} rows; no DB changes.", file=sys.stderr)
        return 0

    ins = 0
    async with engine.begin() as conn:
        for r in rows:
            res = await conn.execute(text(
                "INSERT INTO field_treatments (field_id, field_name, treatment_date, season, "
                "crop, operation, op_category, product, dose, area_ha, note, source) VALUES "
                "(:field_id,:field_name,:treatment_date,:season,:crop,:operation,:op_category,"
                ":product,:dose,:area_ha,:note,'cropwise_api') "
                "ON CONFLICT (field_name, treatment_date, operation, product, dose, area_ha) "
                "DO NOTHING"), r)
            ins += res.rowcount or 0
        # API is the source of truth: retire the manual import rows for any field
        # the API now covers (keep bot-logged ops and uncovered fields untouched).
        retired = (await conn.execute(text(
            "DELETE FROM field_treatments WHERE source IN "
            "('cropwise_multiprotocol','import','manual') AND field_id IN "
            "(SELECT DISTINCT field_id FROM field_treatments WHERE source='cropwise_api')"))).rowcount
    print(f"inserted {ins} new cropwise_api rows; retired {retired} manual rows.", file=sys.stderr)
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry", action="store_true", help="preview, no DB changes")
    ap.add_argument("--field", default=None, help="limit to one field (testing)")
    args = ap.parse_args()
    if not HEADERS["X-User-Api-Token"]:
        print("✗ CROPWISE_OPERATIONS_TOKEN not set.", file=sys.stderr)
        return 1
    return asyncio.run(run(args.dry, args.field))


if __name__ == "__main__":
    sys.exit(main())
