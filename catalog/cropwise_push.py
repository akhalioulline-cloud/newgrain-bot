"""Push a bot-logged operation INTO Cropwise as a new agro_operation — the reverse
of cropwise_ops_sync. Confirmed write-capable (POST → 422 validation, not 403).

Required by the API: field_id, field_shape_id, work_type_id (+ dates/area). Products
go in application_mix_items (applicable_type/applicable_id + planned_rate + unit_id).
We stamp an idempotency_key derived from the local treatment so the create is
dedupe-safe and the weekly pull can recognise our own pushes.

Field/product/work_type are matched to Cropwise's dictionaries the same way the
read sync matched them (our field names mirror Cropwise's "Поле N · Группа").
Unmatched product → per the founder's choice we still create the operation but
leave the product out and flag it (returned in `warnings`).

CLI (validate before wiring into the bot):
  python -m catalog.cropwise_push --note "опрыскал поле 121 корсаром 1.5 л/га" --dry
  python -m catalog.cropwise_push --note "..." --post    # REAL create — owner-run
"""
import argparse
import asyncio
import hashlib
import re
import sys
import time
from datetime import date, datetime, timedelta

import requests

from bot.db import resolve_field
from bot.parse_op import parse_operation
from catalog.cropwise_ops_sync import BASE, HEADERS, _all, _lead_int, _norm, _parse_date

# our op_category -> default Cropwise work_type id
WT_BY_CAT = {"protection": 1, "fertilizer": 2, "sowing": 3, "harvest": 7,
             "tillage": 11, "other": 6}
# operation free-text keyword -> specific work_type id (overrides the category default)
WT_BY_KW = [("опрыск", 1), ("гербицид", 1), ("фунгицид", 1), ("инсектицид", 1), ("сзр", 1),
            ("разбрас", 2), ("подкорм", 2), ("внесен", 2), ("удобр", 2),
            ("сев", 3), ("посев", 3), ("посадк", 3),
            ("уборк", 7), ("урожай", 7), ("намолот", 7),
            ("дисков", 9), ("пахот", 10), ("вспаш", 10), ("культив", 11),
            ("боронов", 13), ("прикат", 14), ("глубокорыхл", 12), ("лущен", 9),
            ("междурядн", 15), ("паров", 11), ("выравнив", 11)]

TYPE_BY_DICT = [("Chemical", "chemicals"), ("Fertilizer", "fertilizers"), ("Seed", "seeds")]


def _norm_prod(p):
    s = (p or "").lower().strip()
    s = re.sub(r"\(.*?\)", "", s)
    s = s.split(",")[0].replace("ё", "е")
    s = re.sub(r"""[«»"„“”'`]""", "", s)     # normalize away quote variants
    return " ".join(s.split()).strip()


def _match_product(name, prods):
    """Map a product name → (applicable_type, id, base_unit_id). Exact normalized
    match first; else a UNIQUE substring match so a short variety name («Гранова»)
    still finds «Семена яровой пшеницы Гранова РС-1». None if ambiguous or no match."""
    key = _norm_prod(name)
    if not key:
        return None
    if key in prods:
        return prods[key]
    if len(key) >= 4:
        hits = [v for k, v in prods.items() if key in k or k in key]
        if len(hits) == 1:
            return hits[0]
    return None


def _split_dose(dose):
    """'1.5 л/га' -> (1.5, 'л/га'); '0,15 ц/га' -> (0.15, 'ц/га'); None-safe."""
    if not dose:
        return None, None
    m = re.match(r"\s*([\d.,]+)\s*(.*)$", str(dose))
    if not m:
        return None, None
    try:
        rate = float(m.group(1).replace(",", "."))
    except ValueError:
        return None, None
    return rate, (m.group(2).strip().lower() or None)


def load_catalogs():
    """Cropwise dictionaries needed to build a create payload."""
    groups = {g["id"]: g["name"] for g in _all("field_groups")}
    prods = {}  # norm name -> (applicable_type, id, base_unit_id)
    for atype, path in TYPE_BY_DICT:
        for p in _all(path):
            unit = p.get("base_inventory_unit_id") or p.get("wh_item_base_unit_id")
            prods.setdefault(_norm_prod(p["name"]), (atype, p["id"], unit))
    by_name, by_numarea = {}, {}
    for f in _all("fields"):
        num = str(f.get("name", "")).strip()
        grp = groups.get(f.get("field_group_id"), "")
        target = f"Поле {num} · {grp}" if grp else f"Поле {num}"
        shape = f.get("field_shape_id") or f.get("current_field_shape_id") or f["id"]
        area = f.get("area") or f.get("calculated_area") or f.get("cadastral_area")
        by_name[_norm(target)] = (f["id"], shape, area)
        if area:
            by_numarea[(_lead_int(num), round(float(area)))] = (f["id"], shape, area)
    return {"prods": prods, "by_name": by_name, "by_numarea": by_numarea}


def resolve_work_type(parsed):
    op = (parsed.get("operation") or "").lower()
    for kw, wid in WT_BY_KW:
        if kw in op:
            return wid
    return WT_BY_CAT.get(parsed.get("category") or "other", 6)


def resolve_cw_field(our_field, cat):
    """our_field = (name, number, area) from our DB -> (field_id, field_shape_id) or None."""
    name, num, area = our_field
    hit = cat["by_name"].get(_norm(name))
    if hit:
        return hit
    if num is not None and area is not None:
        return cat["by_numarea"].get((int(num), round(float(area))))
    return None


def _resolve_date(d):
    """'today'/'yesterday'/ISO/None -> a date (defaults to today)."""
    s = str(d or "today").strip().lower()
    if s in ("today", "сегодня"):
        return date.today()
    if s in ("yesterday", "вчера"):
        return date.today() - timedelta(days=1)
    return _parse_date(d) or date.today()


def build_payload(our_field, parsed, cat, local_key):
    """Return (payload, warnings). our_field = (name, number, area)."""
    warnings = []
    fld = resolve_cw_field(our_field, cat)
    if not fld:
        return None, [f"field not found in Cropwise: {our_field[0]}"]
    field_id, shape_id, cw_area = fld
    cd = _resolve_date(parsed.get("date"))
    iso = cd.isoformat()
    # completed_datetime must be <= now (Cropwise rejects a FUTURE time): for today
    # use a few minutes ago, for a past date use midday.
    if cd >= date.today():
        cdt = (datetime.now() - timedelta(minutes=15)).strftime("%Y-%m-%dT%H:%M:%S")
    else:
        cdt = f"{iso}T12:00:00"
    area = parsed.get("area_ha") or cw_area
    # status=done so a reported operation lands as COMPLETED (not a plan).
    payload = {
        "field_id": field_id,
        "field_shape_id": shape_id,
        "work_type_id": resolve_work_type(parsed),
        "idempotency_key": local_key,
        "status": "done",
        "calc_by": "rate",
        "completed_date": iso,
        "completed_datetime": cdt,
        "completed_percents": 100.0,
        "planned_start_date": iso,
        "planned_end_date": iso,
    }
    if area:
        payload.update(planned_area=float(area), completed_area=float(area))

    product = parsed.get("product")
    if product:
        pm = _match_product(product, cat["prods"])
        if not pm:
            warnings.append(f"product not matched, left for manual entry: {product!r}")
        else:
            atype, pid, unit_id = pm
            rate, unit_lbl = _split_dose(parsed.get("dose"))
            item = {"applicable_type": atype, "applicable_id": pid, "rate_basis": "per_area"}
            if rate is not None:
                # a 'done' op needs the FACT (applied) values, not just planned —
                # else strict_ami_done_status rejects it. fact_amount = rate × area.
                amount = round(rate * float(area), 4) if area else None
                item.update(planned_rate=rate, planned_value=rate, value=rate, fact_rate=rate)
                if amount is not None:
                    item.update(planned_amount=amount, fact_amount=amount)
            if unit_id:
                item["unit_id"] = unit_id          # the product's own base unit (л/кг/ц…)
            if unit_lbl:
                item["rate_unit_label_per_area"] = unit_lbl
            payload["application_mix_items"] = [item]
    return payload, warnings


def create_operation(payload):
    """THREE steps — operation and внесение are separate Cropwise resources, so a
    single request can't do it (per CropWise support):
      1. POST /agro_operations            → create the operation (planned)
      2. POST /application_mix_items       → add each внесение (fact applied), linked
                                             by agro_operation_id
      3. PUT  /agro_operations/{id}        → mark status=done
    Returns (final_status_code, detail).
    """
    hdr = {**HEADERS, "Content-Type": "application/json"}
    mix = payload.get("application_mix_items", [])
    op_body = {k: v for k, v in payload.items()
               if k not in ("status", "application_mix_items")}
    r = requests.post(f"{BASE}/agro_operations", headers=hdr, json={"data": op_body}, timeout=90)
    if r.status_code not in (200, 201):
        return r.status_code, r.text
    op_id = r.json()["data"]["id"]
    for it in mix:                                   # the внесение(s) as their own resource
        item = {**it, "agro_operation_id": op_id}
        ri = requests.post(f"{BASE}/application_mix_items", headers=hdr,
                           json={"data": item}, timeout=90)
        if ri.status_code not in (200, 201):
            return ri.status_code, f"op {op_id} created but внесение failed: {ri.text[:300]}"
    done = {"status": "done"}
    for k in ("completed_date", "completed_datetime", "completed_percents",
              "completed_area", "calc_by"):
        if k in payload:
            done[k] = payload[k]
    r2 = requests.put(f"{BASE}/agro_operations/{op_id}", headers=hdr,
                      json={"data": done}, timeout=90)
    return r2.status_code, (f"created id={op_id}; внесение×{len(mix)}; "
                            f"mark-done HTTP {r2.status_code}: {r2.text[:300]}")


_CATALOG_CACHE = {"data": None, "ts": 0.0}


def _catalogs_cached(ttl=3600):
    """Cropwise dictionaries, reloaded at most once an hour (the load is heavy —
    several API calls — so we don't refetch on every bot /log)."""
    now = time.time()
    if _CATALOG_CACHE["data"] is None or now - _CATALOG_CACHE["ts"] > ttl:
        _CATALOG_CACHE["data"] = load_catalogs()
        _CATALOG_CACHE["ts"] = now
    return _CATALOG_CACHE["data"]


def push_treatment(field_name, field_area, parsed):
    """Bot entry point: create a completed agro_operation in Cropwise from a logged
    op. `parsed` has category/operation/product/dose/area_ha/date. Sync (requests) —
    call via asyncio.to_thread. Returns (ok: bool, russian_message). Never raises for
    a Cropwise problem; the local history row is already saved by the caller."""
    if not HEADERS["X-User-Api-Token"]:
        return False, "CropWise не настроен"
    try:
        cat = _catalogs_cached()
        our_field = (field_name, _lead_int(field_name), field_area)
        payload, warnings = build_payload(our_field, parsed, cat, _key(our_field, parsed))
        if payload is None:
            return False, "поле не найдено в CropWise"
        code, detail = create_operation(payload)
    except Exception as exc:
        return False, f"ошибка отправки в CropWise: {exc}"
    if code not in (200, 201):
        return False, f"CropWise вернул ошибку ({code})"
    if any("product not matched" in w for w in warnings):
        return True, "отправлено в CropWise (препарат не распознан — впишите внесение вручную)"
    return True, "отправлено в CropWise"


async def _resolve_our_field(field_ref, farm_id=None):
    """Our DB field (name, leading-number, area) from a parsed field reference,
    via the same resolver the bot uses (handles 'Поле 121/140' vs 'Поле N · Группа')."""
    row = await resolve_field(str(field_ref or ""), farm_id)
    if not row:
        return None
    return (row["name"], _lead_int(row["name"]), row["area_ha"])


def _key(our_field, parsed):
    raw = "|".join(str(x) for x in (our_field[0], parsed.get("date"),
                                    parsed.get("operation"), parsed.get("product"),
                                    parsed.get("dose")))
    return "flagleaf-" + hashlib.sha1(raw.encode()).hexdigest()[:24]


async def _cli(note, do_post):
    parsed = await parse_operation(note)
    print("parsed:", parsed, file=sys.stderr)
    our_field = await _resolve_our_field(parsed.get("field"))
    if not our_field:
        print(f"✗ could not resolve our field from {parsed.get('field')!r}", file=sys.stderr)
        return 1
    cat = load_catalogs()
    payload, warnings = build_payload(our_field, parsed, cat, _key(our_field, parsed))
    for w in warnings:
        print("⚠", w, file=sys.stderr)
    if payload is None:
        return 1
    import json
    print("payload:\n" + json.dumps(payload, ensure_ascii=False, indent=2))
    if not do_post:
        print("\n[dry] not posting.", file=sys.stderr)
        return 0
    code, body = create_operation(payload)
    print(f"\nPOST agro_operations -> HTTP {code}", file=sys.stderr)
    print(body[:800], file=sys.stderr)
    return 0 if code in (200, 201) else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--note", help="voice/NL operation note to parse + push")
    ap.add_argument("--post", action="store_true", help="REALLY create it in Cropwise (else dry)")
    ap.add_argument("--delete", help="delete an agro_operation by id (test cleanup)")
    args = ap.parse_args()
    if not HEADERS["X-User-Api-Token"]:
        print("✗ CROPWISE_OPERATIONS_TOKEN not set", file=sys.stderr)
        return 1
    if args.delete:
        r = requests.delete(f"{BASE}/agro_operations/{args.delete}", headers=HEADERS, timeout=60)
        print(f"DELETE {args.delete} -> HTTP {r.status_code}", file=sys.stderr)
        print(r.text[:300], file=sys.stderr)
        return 0 if r.status_code in (200, 204) else 1
    if not args.note:
        print("need --note or --delete", file=sys.stderr)
        return 1
    return asyncio.run(_cli(args.note, args.post))


if __name__ == "__main__":
    sys.exit(main())
