"""Audit: would the bot correctly handle every operation in the CropWise history?

Runs all distinct products / operations / fields from field_treatments
(source='cropwise_api') through the SAME mapping + validation logic the bot uses
when an agronomist logs an op, and reports where it would stumble:
  - products the CropWise matcher does NOT recognise  → "препарат не распознан"
  - operations that fall through to work_type "Другое"
  - fields that don't resolve to a CropWise field
  - how many rows would be flagged incomplete (clarification needed) and why

Read-only. Run in the bot container:
  docker compose -f docker-compose.prod.yml run --rm -T bot python -m catalog.oplog_audit
"""
import asyncio
import sys

from sqlalchemy import text

from bot.db import engine
from catalog.cropwise_push import (_lead_int, _norm, _norm_prod, load_catalogs,
                                   resolve_cw_field, resolve_work_type)


def _missing(category, product, dose):
    """Mirror of handlers._op_missing for a complete-field op (field assumed known)."""
    miss = []
    if category in ("protection", "fertilizer", "sowing"):
        if not product:
            miss.append("product")
        elif not dose:
            miss.append("dose")
    return miss


async def main():
    print("loading CropWise catalogs…", file=sys.stderr)
    cat = load_catalogs()
    async with engine.connect() as conn:
        prods = (await conn.execute(text(
            "SELECT product, count(*) c FROM field_treatments WHERE source='cropwise_api' "
            "AND product IS NOT NULL AND product<>'' GROUP BY product ORDER BY c DESC"))).all()
        ops = (await conn.execute(text(
            "SELECT operation, op_category, count(*) c FROM field_treatments "
            "WHERE source='cropwise_api' GROUP BY operation, op_category ORDER BY c DESC"))).all()
        flds = (await conn.execute(text(
            "SELECT id, name, area_ha FROM fields"))).all()
        rows = (await conn.execute(text(
            "SELECT op_category, product, dose, count(*) c FROM field_treatments "
            "WHERE source='cropwise_api' GROUP BY op_category, product, dose"))).all()

    # 1. PRODUCT recognition (weighted by how often each product is used)
    m_prod = m_rows = u_prod = u_rows = 0
    unmatched = []
    for p, c in prods:
        if _norm_prod(p) in cat["prods"]:
            m_prod += 1; m_rows += c
        else:
            u_prod += 1; u_rows += c; unmatched.append((p, c))
    print("\n=== PRODUCT recognition ===")
    print(f"  distinct products: {m_prod} matched / {u_prod} not — "
          f"{round(100*m_prod/max(m_prod+u_prod,1))}%")
    print(f"  by usage (rows):   {m_rows} matched / {u_rows} not — "
          f"{round(100*m_rows/max(m_rows+u_rows,1))}%")
    if unmatched:
        print(f"  top UNRECOGNISED products (add as aliases):")
        for p, c in unmatched[:25]:
            print(f"    {c:>5}×  {p}")

    # 2. OPERATION → work_type
    other = [(o, oc, c) for o, oc, c in ops if resolve_work_type({"operation": o, "category": oc}) == 6]
    print("\n=== OPERATION → work_type ===")
    print(f"  distinct operations: {len(ops)}; fall through to 'Другое': {len(other)}")
    for o, oc, c in other[:20]:
        print(f"    {c:>5}×  {o!r} [{oc}]")

    # 3. FIELD resolution (our fields → CropWise field)
    f_un = [(n, fid) for fid, n, a in flds
            if resolve_cw_field((n, _lead_int(n), float(a) if a is not None else None), cat) is None]
    print("\n=== FIELD resolution ===")
    print(f"  fields: {len(flds)-len(f_un)}/{len(flds)} resolve to a CropWise field")
    for n, fid in f_un[:20]:
        print(f"    unresolved: {n} (id {fid})")

    # 4. Clarification: how many rows would the bot flag incomplete
    need = {}
    total = 0
    for oc, p, d, c in rows:
        total += c
        for slot in _missing(oc, p, d):
            need[slot] = need.get(slot, 0) + c
    print("\n=== Clarification (would-ask) over all rows ===")
    print(f"  total rows: {total}")
    for slot, c in sorted(need.items(), key=lambda x: -x[1]):
        print(f"    would ask for {slot}: {c} rows")
    print("  (complete rows ask nothing.)")


if __name__ == "__main__":
    asyncio.run(main())
