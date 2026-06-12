"""Import digitized field treatment/operation history into field_treatments.

Source is the farm's own records — a CropWise/1C export or the filled template
(catalog/treatment_history_template.csv). Robust to Russian-Excel quirks:
UTF-8 / cp1251, ';' or ',' delimiter, comma-decimals. Russian column headers are
mapped to table columns; the field name is matched to the fields table.

Run:  docker compose -f docker-compose.prod.yml run --rm -T bot \
        python -m catalog.ingest_treatments /path/to/history.csv [--replace]
Default appends; --replace TRUNCATEs first (use for a clean reload).
"""
import argparse
import asyncio
import csv
import io
import re
import sys
from datetime import datetime

from sqlalchemy import text

from bot.db import engine

# normalized Russian header -> table column
HEADER_MAP = {
    "поле": "field_name",
    "дата": "treatment_date", "дата обработки": "treatment_date",
    "сезон": "season", "год": "season",
    "культура": "crop",
    "операция": "operation", "вид обработки": "operation",
    "категория": "op_category", "op_category": "op_category",
    "препарат": "product", "продукт": "product",
    "действующее вещество": "active_substance", "дв": "active_substance",
    "объект": "target", "вредный объект": "target", "цель": "target",
    "норма": "dose", "норма применения": "dose", "доза": "dose",
    "площадь": "area_ha", "площадь_га": "area_ha", "площадь, га": "area_ha", "га": "area_ha",
    "фенофаза": "phenophase", "фаза": "phenophase",
    "условия": "conditions",
    "стоимость": "cost", "цена": "cost",
    "результат": "result",
    "исполнитель": "operator", "агроном": "operator",
    "примечание": "note", "комментарий": "note",
    "источник": "source", "source": "source",
    "площадь_поля": "field_area",  # transient: for number+area field matching
}

# Natural key for dedup — must mirror the unique index in migration 0018.
NATKEY = ("field_name", "treatment_date", "operation", "product", "dose", "area_ha")


def _norm(h):
    return (h or "").strip().lower().replace("ё", "е")


def _lead_int(name):
    """Leading integer of a field name ('Поле 125 · Хлевище' -> 125)."""
    m = re.match(r"\D*(\d+)", name or "")
    return int(m.group(1)) if m else None


def _date(s):
    s = (s or "").strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y", "%d.%m.%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def _num(s):
    s = (s or "").strip().replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _read(path):
    raw = open(path, "rb").read()
    data = None
    for enc in ("utf-8-sig", "cp1251", "utf-8"):
        try:
            data = raw.decode(enc); break
        except UnicodeDecodeError:
            continue
    if data is None:
        raise RuntimeError("could not decode the CSV (tried utf-8/cp1251)")
    delim = ";" if data[:2000].count(";") > data[:2000].count(",") else ","
    out = []
    for row in csv.DictReader(io.StringIO(data), delimiter=delim):
        rec = {}
        for h, v in row.items():
            col = HEADER_MAP.get(_norm(h))
            if col and v and v.strip():
                rec[col] = v.strip()
        if rec:
            out.append(rec)
    return out


async def _load(records, replace):
    inserted = skipped = unmatched = 0
    async with engine.begin() as conn:
        fields = (await conn.execute(text("SELECT id, name, area_ha FROM fields"))).all()
        fmap = {_norm(n): i for i, n, _a in fields}
        # Fallback key: leading field number + rounded area (mirrors
        # ingest_fields' pilot matching), so a treatment file still links to
        # its field even when the source name doesn't string-match exactly.
        by_numarea = {}
        for fid, n, a in fields:
            li = _lead_int(n)
            if li is not None and a is not None:
                by_numarea[(li, round(float(a)))] = fid
        if replace:
            await conn.execute(text("TRUNCATE field_treatments RESTART IDENTITY"))
        conflict = ", ".join(NATKEY)
        for r in records:
            r = dict(r)
            field_area = _num(r.pop("field_area", None))
            if "treatment_date" in r:
                r["treatment_date"] = _date(r["treatment_date"])
            if "area_ha" in r:
                r["area_ha"] = _num(r["area_ha"])
            if "season" in r:
                digits = re.sub(r"\D", "", r["season"])
                r["season"] = int(digits) if digits else None
            elif r.get("treatment_date"):
                r["season"] = r["treatment_date"].year
            name = r.get("field_name")
            fid = fmap.get(_norm(name))
            if fid is None and name:  # fall back to number + area
                area = field_area if field_area is not None else r.get("area_ha")
                li = _lead_int(name)
                if li is not None and area is not None:
                    fid = by_numarea.get((li, round(float(area))))
            r["field_id"] = fid
            if name and fid is None:
                unmatched += 1
            r.setdefault("source", "import")
            cols = list(r.keys())
            # ON CONFLICT DO NOTHING against the natural-key index (migration
            # 0018) makes re-runs idempotent and an API sync collision-free —
            # an identical operation already present is skipped, not duplicated.
            res = await conn.execute(
                text(f"INSERT INTO field_treatments ({', '.join(cols)}) "
                     f"VALUES ({', '.join(':' + c for c in cols)}) "
                     f"ON CONFLICT ({conflict}) DO NOTHING"),
                r,
            )
            if res.rowcount:
                inserted += 1
            else:
                skipped += 1
    return inserted, skipped, unmatched


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("csv_path")
    ap.add_argument("--replace", action="store_true", help="TRUNCATE before loading")
    args = ap.parse_args()

    records = _read(args.csv_path)
    if not records:
        print("no rows parsed — check headers/delimiter.", file=sys.stderr)
        return 1
    print(f"parsed {len(records)} record(s); loading…", file=sys.stderr)
    inserted, skipped, unmatched = asyncio.run(_load(records, args.replace))
    print(f"inserted {inserted}; skipped {skipped} already-present duplicate(s); "
          f"{unmatched} had a field name not matching the fields table "
          f"(kept as text, field_id=NULL).", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
