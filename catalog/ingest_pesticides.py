"""Ingest the Минсельхоз state pesticide catalog into pesticide_applications.

Source: opendata.mcx.ru pesticide registry (the neutral, legal recommendation
source-of-truth per LICENSING.md §3). The published file is a ZIP containing a
~16 MB XML: 2584 products, each with active substances and a set of
crop × target application records. We flatten to one row per
(product × application record) so the agent can query "for <crop> + <target>,
which registered products at what rate?".

By default we ingest only the PILOT crops (wheat / sunflower / soy) to keep the
table small and relevant; pass --all to ingest the whole catalog. Re-running
TRUNCATEs and reloads (the catalog is a full snapshot, refreshed ~monthly).

Run:  docker compose -f docker-compose.prod.yml run --rm -T bot python -m catalog.ingest_pesticides
"""
import argparse
import asyncio
import io
import re
import sys
import zipfile
from datetime import datetime

import requests
import xml.etree.ElementTree as ET
from sqlalchemy import text

from bot.db import engine

DATASET = "http://opendata.mcx.ru/opendata/7708075454-pestitsidy"
# Pilot crops — matched as case-insensitive substrings of Kultura_obrabatyvaemyy_obekt
# (covers "Пшеница озимая/яровая", "Подсолнечник", "Соя").
PILOT_CROP_STEMS = ("пшениц", "подсолнечник", "соя")


def _latest_data_url() -> str:
    html = requests.get(DATASET, timeout=60).text
    urls = re.findall(r"https?://[^\"']+data-\d{8}-\d+-structure-\d{8}\.xml", html)
    if not urls:
        rels = re.findall(r"data-\d{8}-\d+-structure-\d{8}\.xml", html)
        urls = [f"{DATASET}/{r}" for r in rels]
    if not urls:
        raise RuntimeError("could not find a data-*.xml file on the dataset page")
    urls = sorted(set(urls), key=lambda u: re.search(r"data-(\d{8})", u).group(1))
    return urls[-1]


def _download_xml(url: str) -> bytes:
    blob = requests.get(url, timeout=180).content
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        return z.read(z.namelist()[0])


def _t(elem, path):
    v = elem.findtext(path)
    return v.strip() if v else None


def _parse_date(s):
    if not s:
        return None
    try:
        return datetime.strptime(s.strip(), "%d.%m.%Y").date()
    except ValueError:
        return None


def _rows(xml_bytes: bytes, ingest_all: bool):
    """Yield one dict per (product × application record)."""
    for _evt, p in ET.iterparse(io.BytesIO(xml_bytes), events=("end",)):
        if p.tag != "items":
            continue
        category = _t(p, "fulldataset3/item/naznachenie")
        name = _t(p, "Naimenovanie/item")
        # active substances (may be several)
        subs = []
        for s in p.findall("fulldataset1/item"):
            dv = _t(s, "Deystvuyushee_veshestvo")
            if not dv:
                continue
            conc = _t(s, "Koncentraciya")
            unit = _t(s, "Ed_Izveren_1")
            subs.append(f"{dv} ({conc} {unit})" if conc else dv)
        product = dict(
            product_name=name,
            category=category,
            formulation=_t(p, "Preparativnaya_forma/item"),
            active_substances="; ".join(subs) or None,
            registrant=_t(p, "Registrant/item"),
            hazard_class=_t(p, "Klass_opasnosti/item"),
            reg_number=_t(p, "Nomer_gosudarstvennoy_registracii/item"),
            reg_valid_until=_parse_date(_t(p, "Srok_registracii_Po/item")),
            status=_t(p, "Status_gosudarstvennoy_registracii/item"),
        )
        for a in p.findall("fulldataset2/item"):
            crop = _t(a, "Kultura_obrabatyvaemyy_obekt")
            if not ingest_all:
                low = (crop or "").lower()
                if not any(stem in low for stem in PILOT_CROP_STEMS):
                    continue
            rate = _t(a, "Norma_primeneniya")
            unit = _t(a, "Ed_Izveren_3")
            yield {
                **product,
                "crop": crop,
                "target": _t(a, "Vrednyy_obekt_naznachenie"),
                "rate": (f"{rate} {unit}".strip() if rate else None),
                "application_method": _t(a, "Sposob_i_vremya_obrabotki"),
                "notes": _t(a, "Osobennosti_primeneniya"),
                "avia_allowed": _t(a, "Razreshenie_avia_obrabotok"),
                "waiting_period_freq": _t(a, "Srok_ozhidaniya_kratnost_obrabotok"),
            }
        p.clear()


_COLS = ["product_name", "category", "formulation", "active_substances", "registrant",
         "hazard_class", "reg_number", "reg_valid_until", "status", "crop", "target",
         "rate", "application_method", "notes", "avia_allowed", "waiting_period_freq"]
_INSERT = text(
    "INSERT INTO pesticide_applications (" + ", ".join(_COLS) + ") VALUES ("
    + ", ".join(f":{c}" for c in _COLS) + ")"
)


async def _load(rows):
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE pesticide_applications RESTART IDENTITY"))
        for i in range(0, len(rows), 500):
            await conn.execute(_INSERT, rows[i:i + 500])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--all", action="store_true", help="ingest all crops (default: pilot crops only)")
    args = ap.parse_args()

    url = _latest_data_url()
    print(f"latest catalog file: {url}", file=sys.stderr)
    xml_bytes = _download_xml(url)
    print(f"parsing {len(xml_bytes)//1024} KB of XML…", file=sys.stderr)
    rows = list(_rows(xml_bytes, args.all))
    if not rows:
        print("no rows parsed — aborting (not truncating).", file=sys.stderr)
        return 1
    crops = sorted({r["crop"] for r in rows})
    print(f"{len(rows)} application rows across {len(crops)} crop variants "
          f"({'ALL' if args.all else 'pilot crops'}).", file=sys.stderr)
    asyncio.run(_load(rows))
    print("loaded into pesticide_applications.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
