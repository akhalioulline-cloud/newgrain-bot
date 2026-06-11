"""Report MoA-map coverage of the pesticide catalog: how many distinct active
substances (and frequency-weighted occurrences) get a HRAC/FRAC/IRAC class.
Unclassified are mostly agrochemicals/biostimulants/micronutrients (no MoA).

Run: docker compose -f docker-compose.prod.yml run --rm -T bot python -m catalog.moa_coverage
"""
import asyncio
import re
import sys
from collections import Counter

from sqlalchemy import text

from bot.db import engine
from bot.moa import classify


async def run():
    async with engine.connect() as conn:
        rows = (await conn.execute(text(
            "SELECT active_substances FROM pesticide_applications "
            "WHERE active_substances IS NOT NULL"))).scalars().all()
    subs = Counter()
    for r in rows:
        for seg in r.split(";"):
            name = re.sub(r"\(.*?\)", "", seg).strip().lower()
            if name:
                subs[name] += 1
    distinct = len(subs)
    total = sum(subs.values())
    cls_d = sum(1 for s in subs if classify(s))
    cls_t = sum(n for s, n in subs.items() if classify(s))
    print(f"distinct substances: {distinct} | classified: {cls_d} ({100 * cls_d // distinct}%)")
    print(f"occurrences:         {total} | classified: {cls_t} ({100 * cls_t // total}%)")
    unc = sorted(((n, s) for s, n in subs.items() if not classify(s)), reverse=True)
    print("\ntop-20 unclassified by frequency (expect agrochemicals/biostimulants):")
    for n, s in unc[:20]:
        print(f"  {n:4d}  {s}")


if __name__ == "__main__":
    asyncio.run(run())
    sys.exit(0)
