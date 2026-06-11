"""Fill field_treatments.active_substance by matching each product's trade name
to the pesticide catalog (pesticide_applications.active_substances).

CropWise trade names carry formulation codes and concentrations ("Корсар, ВРК",
"Борей нео СК (125+100+50 г/л)", "Фастак (архив)"); we normalize those off and
match the core name to the catalog (which stores the active substance per
registration). Idempotent; reports match rate + unmatched products.

Run: docker compose -f docker-compose.prod.yml run --rm -T bot python -m catalog.enrich_active_substances
"""
import asyncio
import re
import sys
from collections import Counter

from sqlalchemy import text

from bot.db import engine

# Russian pesticide formulation abbreviations (trailing tokens to strip)
FORMS = {"сэ", "кэ", "вр", "врк", "ск", "кс", "вдг", "врг", "мд", "мэ", "кмэ", "мкэ",
         "сп", "вск", "вгр", "ж", "вэ", "мкс", "ккр", "врп", "таб", "пс", "тпс",
         "вср", "рп", "сзр", "ктс", "вднг", "врд", "сус", "конц", "мкг"}


def _norm(p):
    s = (p or "").lower().strip()
    s = re.sub(r"\(.*?\)", "", s)   # drop (900 г/л) / (архив) / (125+100+50 г/л)
    s = s.split(",")[0]             # drop ", СЭ" etc.
    s = s.replace("ё", "е")
    toks = [t for t in s.split() if t]
    while toks and toks[-1] in FORMS:
        toks.pop()
    return " ".join(toks).strip()


async def run():
    async with engine.begin() as conn:
        # build normalized catalog map: norm(product_name) -> most common active_substances
        rows = (await conn.execute(text(
            "SELECT product_name, active_substances FROM pesticide_applications "
            "WHERE active_substances IS NOT NULL"))).all()
        by_norm = {}
        for pn, act in rows:
            by_norm.setdefault(_norm(pn), Counter())[act] += 1
        cat = {k: c.most_common(1)[0][0] for k, c in by_norm.items() if k}

        products = (await conn.execute(text(
            "SELECT DISTINCT product FROM field_treatments "
            "WHERE op_category='protection' AND product IS NOT NULL AND product<>''"))).scalars().all()

        matched, unmatched = {}, []
        for p in products:
            core = _norm(p)
            act = cat.get(core)
            if not act:  # prefix fallback
                for k, v in cat.items():
                    if core and (k.startswith(core) or core.startswith(k)):
                        act = v; break
            if act:
                matched[p] = act
            else:
                unmatched.append(p)

        for p, act in matched.items():
            await conn.execute(text(
                "UPDATE field_treatments SET active_substance=:a WHERE product=:p AND op_category='protection'"),
                {"a": act, "p": p})

    print(f"protection products: {len(products)} | matched: {len(matched)} | unmatched: {len(unmatched)}",
          file=sys.stderr)
    if matched:
        print("\nsample matches:", file=sys.stderr)
        for p, a in list(matched.items())[:10]:
            print(f"  {p}  ->  {a}", file=sys.stderr)
    if unmatched:
        print("\nunmatched (no д.в. in catalog — likely off-pilot/archived/typo):", file=sys.stderr)
        print("  " + "; ".join(sorted(unmatched)), file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(run())
    sys.exit(0)
