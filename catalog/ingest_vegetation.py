"""Load the weekly vegetation+weather CSV into vegetation_weekly.

Columns: week-start date, week №, NDVI, temps, soil-surface temp, precip, snow.
Idempotent (ON CONFLICT (field_id,week_start,source) DO NOTHING).

Run: docker compose -f docker-compose.prod.yml run --rm -T -v /tmp/v.csv:/data.csv \
       bot python -m catalog.ingest_vegetation /data.csv --field "Поле 76/108" --source cropwise
"""
import argparse
import asyncio
import csv
import io
import sys
from datetime import datetime

from sqlalchemy import text

from bot.db import engine

METRICS = ["week_no", "ndvi", "t_avg", "t_min", "t_max", "soil_surface_t", "precip_mm", "snow_mm"]


def _num(s):
    s = str(s or "").strip().replace(" ", "").replace(",", ".")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _date(s):
    s = str(s or "").strip()
    for f in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            pass
    return None


def _match(h):
    t = (h or "").strip().lower()
    if "недел" in t and ("дата" in t or "начал" in t):
        return "week_start"
    if "номер" in t and "недел" in t:
        return "week_no"
    if "ndvi" in t:
        return "ndvi"
    if "поверхност" in t and "почв" in t:
        return "soil_surface_t"
    if "темп" in t:
        if "средн" in t:
            return "t_avg"
        if "мин" in t:
            return "t_min"
        if "макс" in t:
            return "t_max"
    if "осадк" in t:
        return "precip_mm"
    if "снег" in t:
        return "snow_mm"
    return None


def _read(path):
    raw = open(path, "rb").read()
    data = None
    for enc in ("utf-8-sig", "cp1251", "utf-8"):
        try:
            data = raw.decode(enc); break
        except UnicodeDecodeError:
            continue
    delim = ";" if data[:2000].count(";") > data[:2000].count(",") else ","
    reader = csv.reader(io.StringIO(data), delimiter=delim)
    header = next(reader)
    idx = {}
    for i, h in enumerate(header):
        col = _match(h)
        if col and col not in idx:
            idx[col] = i
    if "week_start" not in idx:
        raise RuntimeError(f"no week-start column found; headers={header}")
    rows = []
    for r in reader:
        ws = _date(r[idx["week_start"]]) if idx["week_start"] < len(r) else None
        if not ws:
            continue
        rec = {"week_start": ws}
        for m in METRICS:
            v = _num(r[idx[m]]) if m in idx and idx[m] < len(r) else None
            rec[m] = int(v) if (m == "week_no" and v is not None) else v
        rows.append(rec)
    return rows


_COLS = ["field_id", "week_start"] + METRICS + ["source"]
_INSERT = text(
    "INSERT INTO vegetation_weekly (" + ", ".join(_COLS) + ") VALUES ("
    + ", ".join(f":{c}" for c in _COLS) + ") ON CONFLICT (field_id, week_start, source) DO NOTHING"
)


async def _load(rows, field, source):
    async with engine.begin() as conn:
        fid = (await conn.execute(text("SELECT id FROM fields WHERE name=:n"), {"n": field})).scalar()
        for r in rows:
            r["field_id"] = fid
            r["source"] = source
        for i in range(0, len(rows), 1000):
            await conn.execute(_INSERT, rows[i:i + 1000])
        return fid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path")
    ap.add_argument("--field", required=True)
    ap.add_argument("--source", default="cropwise")
    args = ap.parse_args()
    rows = _read(args.csv_path)
    if not rows:
        print("no rows.", file=sys.stderr); return 1
    nd = sum(1 for r in rows if r.get("ndvi") is not None)
    print(f"{len(rows)} weekly rows ({rows[0]['week_start']} … {rows[-1]['week_start']}), {nd} with NDVI; loading…", file=sys.stderr)
    fid = asyncio.run(_load(rows, args.field, args.source))
    print(f"loaded (field_id={fid}).", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
