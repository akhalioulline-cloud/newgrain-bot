"""Load a daily-weather CSV into weather_daily.

Keyword header-matching handles both source layouts (Valujki CSV and the
meteoblue export converted to CSV): temps, precip, snow, wind, 3 soil-moisture
layers, humidity, solar. Rows with no metric values are skipped. Idempotent
(ON CONFLICT (field_id,date,source) DO NOTHING).

Run: docker compose -f docker-compose.prod.yml run --rm -T -v /tmp/w.csv:/data.csv \
       bot python -m catalog.ingest_weather /data.csv --field "Поле 76/108" --source valujki
"""
import argparse
import asyncio
import csv
import io
import sys
from datetime import datetime

from sqlalchemy import text

from bot.db import engine

METRICS = ["t_avg", "t_min", "t_max", "precip_mm", "snow_mm", "wind_ms",
           "soil_moist_top", "soil_moist_mid", "soil_moist_deep",
           "rel_humidity", "solar_wm2", "soil_surface_t"]


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
    if t.startswith("дата"):
        return "date"
    if "поверхност" in t and "почв" in t:
        return "soil_surface_t"
    if "влажност" in t and "почв" in t:
        if "280" in t and "1000" in t:
            return "soil_moist_deep"
        if "70" in t and "280" in t:
            return "soil_moist_mid"
        if "70" in t:
            return "soil_moist_top"
        return None
    if "относительн" in t and "влажност" in t:
        return "rel_humidity"
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
    if "ветр" in t:
        return "wind_ms"
    if "излучен" in t:
        return "solar_wm2"
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
    if "date" not in idx:
        raise RuntimeError(f"no date column found; headers={header}")
    rows = []
    for r in reader:
        d = _date(r[idx["date"]]) if idx["date"] < len(r) else None
        if not d:
            continue
        rec = {"date": d}
        for m in METRICS:
            rec[m] = _num(r[idx[m]]) if m in idx and idx[m] < len(r) else None
        if any(rec[m] is not None for m in METRICS):  # skip empty rows
            rows.append(rec)
    return rows


_COLS = ["field_id", "date"] + METRICS + ["source"]
_INSERT = text(
    "INSERT INTO weather_daily (" + ", ".join(_COLS) + ") VALUES ("
    + ", ".join(f":{c}" for c in _COLS) + ") ON CONFLICT (field_id, date, source) DO NOTHING"
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
    ap.add_argument("--source", required=True)
    args = ap.parse_args()
    rows = _read(args.csv_path)
    if not rows:
        print("no non-empty rows.", file=sys.stderr); return 1
    print(f"{len(rows)} weather rows ({rows[0]['date']} … {rows[-1]['date']}); loading…", file=sys.stderr)
    fid = asyncio.run(_load(rows, args.field, args.source))
    print(f"loaded (field_id={fid}, source={args.source}).", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
