"""Spot-check the bot's LLM parser + clarification on REALISTIC phrasings of real ops.

Samples common operations per category from the CropWise history, phrases each the
way an agronomist might (varied word order, short product names), runs the real
`parse_operation`, and grades: does it recover the field / product / category, and
— for cases where we deliberately omit the dose — would the bot ask for it?

Run in the bot container (uses YandexGPT; text only, no photos):
  docker compose -f docker-compose.prod.yml run --rm -T bot python -m catalog.oplog_parse_test
"""
import asyncio
import re
import sys

from sqlalchemy import text

from bot.db import engine, find_fields_by_number, resolve_field
from bot.parse_op import parse_operation
from catalog.cropwise_push import _lead_int, _match_product, _norm_prod, load_catalogs

TPL = {
    "protection": ["опрыскал {f} {p} {d} от сорняков",
                   "обработал поле {f} препаратом {p}, {d}",
                   "{f} поле, {p} {d}"],
    "fertilizer": ["внесли {p} {d} на {f}",
                   "разбросали {p} на поле {f}, {d}"],
    "sowing": ["посеяли {p} на {f}, норма {d}", "сев {p}, поле {f}, {d}"],
    "tillage": ["{o} на поле {f}", "сделали {o}, поле {f}"],
    "harvest": ["убрали поле {f}", "уборка на {f}"],
    "other": ["{o} на поле {f}"],
}


def norm(s):
    return re.sub(r"\s+", " ", (s or "").lower().replace("ё", "е")).strip()


def short_product(p):
    return (p or "").split(",")[0].split("(")[0].strip()


def _missing(category, product, dose):
    if category in ("protection", "fertilizer", "sowing"):
        if not product:
            return ["product"]
        if not dose:
            return ["dose"]
    return []


async def main():
    async with engine.connect() as conn:
        farm_id = (await conn.execute(text(
            "SELECT farm_id FROM fields WHERE farm_id IS NOT NULL LIMIT 1"))).scalar()
        rows = (await conn.execute(text("""
            WITH r AS (
              SELECT field_id, field_name, op_category, operation, product, dose,
                row_number() OVER (PARTITION BY op_category ORDER BY count(*) DESC) rn
              FROM field_treatments WHERE source='cropwise_api' AND field_id IS NOT NULL
              GROUP BY field_id, field_name, op_category, operation, product, dose
            )
            SELECT field_id, field_name, op_category, operation, product, dose
            FROM r WHERE rn <= 5 ORDER BY op_category, rn"""))).all()

    prods = load_catalogs()["prods"]          # for grading via the REAL product matcher
    ok = tot = clar_ok = clar_tot = 0
    for i, (fid, fname, cat, op, prod, dose) in enumerate(rows):
        num = _lead_int(fname)
        sp = short_product(prod) if prod else ""
        tpls = TPL.get(cat, TPL["other"])
        drop_dose = (i % 4 == 3) and cat in ("protection", "fertilizer", "sowing") and dose
        note = tpls[i % len(tpls)].format(
            f=num, p=sp, d=("" if drop_dose else (dose or "")), o=(op or "операция"))
        note = re.sub(r"\s{2,}", " ", note).strip(" ,")
        parsed = await parse_operation(note)
        tot += 1
        if not parsed:
            print(f"  PARSE-FAIL  {note!r}", file=sys.stderr)
            continue
        # Field: did the PARSER read the right number? (which отделение is a separate
        # step the bot now handles by asking, so we don't penalise the parser for it.)
        pnum = _lead_int(str(parsed.get("field") or ""))
        f_ok = pnum is not None and pnum == num
        ambig = len(await find_fields_by_number(farm_id, str(num))) > 1
        # Product: does the REAL matcher recognise it (and land on the same product)?
        pp = parsed.get("product")
        if not prod:
            p_ok = True
        else:
            want, got = _match_product(prod, prods), _match_product(pp or "", prods)
            p_ok = bool(got and (not want or got[1] == want[1]))
        pc = parsed.get("category") or "other"
        c_ok = pc == cat or (pc in ("tillage", "other") and cat in ("tillage", "other"))
        case_ok = f_ok and p_ok and c_ok
        ok += 1 if case_ok else 0
        extra = ""
        if drop_dose:
            clar_tot += 1
            asks = _missing(cat, pp, parsed.get("dose"))
            if "dose" in asks:
                clar_ok += 1
            extra = f"  [dropped dose → asks {asks or 'nothing'}]"
        if ambig and f_ok:
            extra += "  [number repeats → bot asks отделение]"
        flags = ("" if f_ok else f" field✗(got {parsed.get('field')}, exp {num})") + \
                ("" if p_ok else f" product✗(got {pp!r}, exp {sp!r})") + \
                ("" if c_ok else f" cat✗(got {pc}, exp {cat})")
        print(f"  {'OK ' if case_ok else 'MISS'}  {note!r}{flags}{extra}", file=sys.stderr)
    print(f"\n=== parser: {ok}/{tot} fully correct | "
          f"clarification on dropped dose: {clar_ok}/{clar_tot} ===", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
