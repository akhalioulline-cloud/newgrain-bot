"""Parse a «Задания машин» report (the text Евгения pastes from Max) and map it to
CropWise objects, then (optionally) create the agro-operations — one per field, each
with the tank mix + the matched work-type, and the machine + driver attached.

Goal: Евгения pastes the report → the bot creates everything → she checks CropWise.
See docs/cropwise-machine-task-reports.md.

Stage 1 (this file, --dry): parse + resolve + PREVIEW the plan (no writes; safe to run).
Stage 2 (--post): create the operations in CropWise (run by the operator).

  python -m catalog.cropwise_report --dry  --text "<report>"
  python -m catalog.cropwise_report --post --text "<report>"
"""
import argparse
import asyncio
import hashlib
import json
import re
import sys
from datetime import date, datetime, timedelta

import requests

from bot.config import settings
from catalog.cropwise_ops_sync import HEADERS
from catalog.cropwise_push import (_all, _lead_int, _match_product, _norm, _split_dose,
                                   create_operation, load_catalogs)

BASE = "https://operations.cropwise.com/api/v3"


def _norm_txt(s):
    return re.sub(r"\s+", " ", (s or "").lower().replace("ё", "е")).strip()


# ---------- LLM parse of the free-form report ----------
_SYS = (
    "Ты разбираешь отчёт о полевых работах («задание машины»). Верни ТОЛЬКО JSON:\n"
    '{"operation":"<первая строка: вид операции>",'
    '"driver":"<фамилия механизатора>",'
    '"machine_number":"<инвентарный/гос. номер машины, например 6448>",'
    '"machine_type":"<тип машины: самоходка/КамАЗ/ГАЗ/Амазон и т.п.>",'
    '"products":[{"name":"<препарат>","dose":"<норма, напр. 2 л/га>"}],'
    '"fields":["<номер/площадь, напр. 167/104>", ...]}\n'
    "Вторая строка содержит механизатора, машину и её номер в произвольном порядке "
    "(через пробел или дефис). driver — это ВСЕГДА человек (фамилия, и имя/отчество/инициалы "
    "если они указаны, например «Шапаренко Сергей Петрович»), никогда не часть названия "
    "машины. Примеры второй строки:\n"
    "«Яровой самоходка 6448» → driver=Яровой, machine_type=самоходка, machine_number=6448\n"
    "«Черных 5628-Рсм 3000» → driver=Черных, machine_number=5628, machine_type=Рсм 3000\n"
    "«6439-Шапаренко-Amazon 5.200» → machine_number=6439, driver=Шапаренко, machine_type=Amazon 5.200\n"
    "«Гаврилов КамАЗ 928» → driver=Гаврилов, machine_type=КамАЗ, machine_number=928\n"
    "Препараты — строки вида «Название - доза». Поля — строки вида «число/число» (после "
    "«Поля:» если есть). Если препаратов/полей нет — пустые списки. Отвечай только JSON."
)


async def parse_report(text):
    from bot.parse_op import _clean  # reuse the json/markdown stripper
    if not (settings.yc_api_key and settings.yc_folder_id):
        return None
    body = {
        "modelUri": f"gpt://{settings.yc_folder_id}/{settings.yc_translate_model}",
        "completionOptions": {"stream": False, "temperature": 0, "maxTokens": 1500},
        "messages": [{"role": "system", "text": _SYS}, {"role": "user", "text": text}],
    }

    def _call():
        r = requests.post("https://llm.api.cloud.yandex.net/foundationModels/v1/completion",
                          headers={"Authorization": f"Api-Key {settings.yc_api_key}"},
                          json=body, timeout=60)
        r.raise_for_status()
        return r.json()["result"]["alternatives"][0]["message"]["text"]

    try:
        raw = await asyncio.to_thread(_call)
        data = json.loads(_clean(raw))
        return data if isinstance(data, dict) else None
    except Exception as exc:
        print(f"parse failed: {exc}", file=sys.stderr)
        return None


# ---------- resolvers against CropWise dictionaries ----------
_WT_STOP = {"и", "в", "на", "с", "по", "для", "от", "под", "до", "за"}


def _wt_tokens(s):
    """Significant tokens of a work-type/operation name: split on ANY non-letter (so
    «Воды+Гербициды» → воды, гербициды), drop stopwords («и») and 1–2-char noise."""
    toks = re.split(r"[^а-яa-z0-9]+", _norm_txt(s))
    return [t for t in toks if len(t) >= 3 and t not in _WT_STOP]


def _wt_tok_match(a, b):
    # exact, or same 5-char stem so «гербицидов» ≈ «гербициды», «опрыскивание» ≈ «опрыскивал»
    return a == b or (len(a) >= 4 and len(b) >= 4 and a[:5] == b[:5])


def match_work_type(op_text, types):
    """Best work_type for an operation line, by stopword-stripped, stem-aware token overlap
    (+1 when a pass number 1/2… matches). Pass the candidate set the caller wants (e.g. only
    agri types for field ops, only non-agri for machine tasks). None below 2 matched tokens."""
    want = _wt_tokens(op_text)
    if not want:
        return None
    digits = re.findall(r"\d", op_text)
    best, score = None, 0
    for w in types:
        toks = _wt_tokens(w["name"])
        s = sum(1 for a in want if any(_wt_tok_match(a, b) for b in toks))
        for d in digits:                       # pass number (1/№1/1-я, 2/2-я …)
            if d in w["name"]:
                s += 1
        if s > score:
            best, score = w, s
    return best if score >= 2 else None


def match_machine(number, mtype, machines):
    num = re.sub(r"\D", "", str(number or ""))
    if not num:
        return None
    for m in machines:                       # number appears in reg/inventory number
        for f in (m.get("registration_number"), m.get("inventory_number"), m.get("name")):
            if f and num in re.sub(r"\s", "", str(f)):
                return m
    return None


# Work that uses a mounted/towed implement (косилка, грейдер, борона…) — for these the bot asks
# WHICH implement; transport (подвоз/перевоз/закачка) doesn't need one.
_IMPL_OP_RE = re.compile(
    r"покос|обкос|кошен|скашив|сенаж|ворош|грабл|грейдир|культив|дисков|боронов|прикат|"
    r"вспаш|чизел|глубокорыхл|лущен|катк|подсыпк", re.I)


def implement_needed(operation: str) -> bool:
    return bool(_IMPL_OP_RE.search(operation or ""))


def _impl_norm(s):                            # keep only letters+digits → «КРН-2,1Б»≈«КРН 2.1»
    return re.sub(r"[^0-9a-zа-я]", "", str(s or "").lower().replace("ё", "е"))


def match_implement(raw, implements):
    """Free text ('СД-105', 'КРН-2.1', 'косилка') → a CropWise implement, matched on model/name."""
    q = _impl_norm(raw)
    if len(q) < 2:
        return None
    for im in implements:
        for f in (im.get("model"), im.get("name")):
            if f and q in _impl_norm(f):
                return im
    return None


def resolve_implement(raw):
    """Resolve typed implement → CropWise implement dict, or None. Sync — call via to_thread."""
    return match_implement(raw, _all("implements")) if raw else None


def driver_matches(driver_raw, users):
    """Best-ranked driver candidates for «Фамилия [Имя] [Отчество]». Among same-surname
    users the given name AND patronymic narrow in order («Шапаренко Сергей» beats «…Евгений»,
    «Купченко Николай Николаевич» beats «…Николай Павлович»); ties break toward ACTIVE
    records (CropWise has many stale 'no_access' namesake dups). Returns [] or [one]
    normally; MORE THAN ONE only for true active full-namesakes the supplied name can't
    separate — the caller should then ask which. Initials work too («…С»)."""
    parts = _norm_txt(driver_raw).split()
    if not parts:
        return []
    surname, given = parts[0], [p.strip(".") for p in parts[1:]]
    scored = []
    for u in users:
        un = _norm_txt(u.get("username"))
        toks = un.split() if un else []
        if not toks or not (toks[0] == surname or surname in un):
            continue
        score = sum(1 for i, g in enumerate(given)
                    if len(toks) > i + 1 and toks[i + 1].startswith(g))
        scored.append((score, u.get("status") != "no_access", u))
    if not scored:
        return []
    scored.sort(key=lambda c: (c[0], c[1]), reverse=True)
    s0, a0, _ = scored[0]
    return [u for (s, a, u) in scored if s == s0 and a == a0]   # all tied for best


def match_driver(driver_raw, users):
    """Single best driver (first of driver_matches), or None."""
    m = driver_matches(driver_raw, users)
    return m[0] if m else None


def _area_of(ref):
    m = re.search(r"/(\d+)", str(ref))
    return int(m.group(1)) if m else None


# ---------- «план агро работ» guard (Евгения's запрет) ----------
# CropWise won't attach an agro-operation to a field unless that field's work type is
# in the field's «план агро работ» for the season — otherwise the operation orphans
# (the task lands empty). So: link a planned operation to its plan, and BLOCK (skip +
# flag) a work type that isn't planned for the field. Trucks (КамАЗ) carry no field
# operation, so they never hit this guard. The plan is keyed by work_type + season-YEAR
# + a groupable that is EITHER the field's отделение (FieldGroup) OR its папка (GroupFolder).
def load_plan_index():
    """Lookup for the CURRENT season: field → отделение/папка, and (work_type, group) →
    plan id. Reused for both linking (set agri_work_plan_id) and blocking (no plan)."""
    year = date.today().year
    field_group_of = {f["id"]: f.get("field_group_id") for f in _all("fields")}
    folder_of = {g["id"]: g.get("group_folder_id") for g in _all("field_groups")}
    plan_for = {}
    for p in _all("agri_work_plans"):
        if p.get("season") != year:
            continue
        plan_for.setdefault((p.get("work_type_id"), p.get("groupable_type"),
                             p.get("groupable_id")), p["id"])
    return {"field_group_of": field_group_of, "folder_of": folder_of, "plan_for": plan_for}


def find_plan(idx, work_type_id, field_id):
    """agri_work_plan id covering this field+work_type this season, or None (→ block).
    Matches at the отделение (FieldGroup) level first, then the папка (GroupFolder)."""
    if work_type_id is None or field_id is None:
        return None
    grp = idx["field_group_of"].get(field_id)
    if grp is None:
        return None
    folder = idx["folder_of"].get(grp)
    return (idx["plan_for"].get((work_type_id, "FieldGroup", grp))
            or (idx["plan_for"].get((work_type_id, "GroupFolder", folder)) if folder else None))


async def build_plan(report):
    """Parse + resolve a report into a SLIM, JSON-serialisable plan (safe for FSM
    storage). Returns (plan, None) or (None, error)."""
    parsed = await parse_report(report)
    if not parsed:
        return None, "не удалось разобрать отчёт"
    cat = load_catalogs()
    wt = match_work_type(parsed.get("operation", ""),
                         [w for w in _all("work_types") if w.get("agri")])
    machine = match_machine(parsed.get("machine_number"), parsed.get("machine_type"), _all("machines"))
    driver = match_driver(parsed.get("driver"), _all("users"))

    products = []
    for p in parsed.get("products", []):
        pm = _match_product(p.get("name", ""), cat["prods"])
        rate, unit = _split_dose(p.get("dose"))
        products.append({"name": p.get("name"), "dose": p.get("dose"), "matched": bool(pm),
                         "atype": pm[0] if pm else None, "aid": pm[1] if pm else None,
                         "unit_id": pm[2] if pm else None, "rate": rate, "unit_label": unit})
    pidx = load_plan_index()
    wt_id = wt["id"] if wt else None
    fields = []
    for f in parsed.get("fields", []):
        cw = cat["by_name"].get(_norm("Поле " + str(f))) or \
            cat["by_numarea"].get((_lead_int(str(f)), _area_of(f)))
        fid = cw[0] if cw else None
        plan_id = find_plan(pidx, wt_id, fid) if fid else None
        fields.append({"ref": str(f), "field_id": fid,
                       "shape": cw[1] if cw else None, "area": cw[2] if cw else None,
                       "plan_id": plan_id, "planned": plan_id is not None})

    plan = {
        "operation": parsed.get("operation"),
        "work_type": {"id": wt["id"], "name": wt["name"]} if wt else None,
        "machine": {"id": machine["id"], "name": machine["name"]} if machine else None,
        "machine_raw": " ".join(x for x in (parsed.get("machine_type"),
                                            str(parsed.get("machine_number") or "")) if x).strip(),
        "driver": {"id": driver["id"], "name": driver.get("username")} if driver else None,
        "driver_raw": parsed.get("driver"),
        "products": products,
        "fields": fields,
    }
    return plan, None


def plan_summary(plan):
    wt, m, d = plan["work_type"], plan["machine"], plan["driver"]
    L = ["📋 Отчёт → CropWise (проверьте):",
         f"Операция: {plan['operation']} → " +
         (f"«{wt['name']}»" if wt else "⚠️ тип не определён"),
         f"Машина: {plan['machine_raw'] or '—'} → " +
         (f"«{m['name']}» (учитывается по GPS отдельно)" if m else "не найдена"),
         f"Механизатор: {plan['driver_raw'] or '—'} → " +
         (f"{d['name']} (ответственный)" if d else "не найден"),
         "Препараты:"]
    for p in plan["products"]:
        L.append(f"  {'✓' if p['matched'] else '⚠️'} {p['name']} {p['dose'] or ''}" +
                 ("" if p["matched"] else " (нет в каталоге)"))
    wt_ok = wt is not None
    creatable = [f for f in plan["fields"] if f["field_id"] and (f["planned"] or not wt_ok)]
    unplanned = [f for f in plan["fields"] if f["field_id"] and wt_ok and not f["planned"]]

    def _mark(f):
        if not f["field_id"]:
            return "⚠️"                       # поле не сопоставлено
        if wt_ok and not f["planned"]:
            return "🚫"                        # вид работ не в плане агро работ
        return "✓"
    L.append(f"Поля ({len(creatable)}/{len(plan['fields'])} к созданию):")
    L.append("  " + ", ".join(_mark(f) + f["ref"] for f in plan["fields"]))
    if unplanned:
        L.append(f"🚫 пропущу — вид работ «{wt['name']}» не в «плане агро работ» этих полей "
                 "(добавьте его в план в CropWise):")
        L.append("  " + ", ".join(f["ref"] for f in unplanned))
    L.append(f"\nСоздать {len(creatable)} агрооперац. с баковой смесью?")
    return "\n".join(L)


def _mix_item(p, area):
    item = {"applicable_type": p["atype"], "applicable_id": p["aid"], "rate_basis": "per_area"}
    rate = p.get("rate")
    if rate is not None:
        amount = round(rate * float(area), 4) if area else None
        item.update(planned_rate=rate, planned_value=rate, value=rate, fact_rate=rate)
        if amount is not None:
            item.update(planned_amount=amount, fact_amount=amount)
    if p.get("unit_id"):
        item["unit_id"] = p["unit_id"]
    if p.get("unit_label"):
        item["rate_unit_label_per_area"] = p["unit_label"]
    return item


def create_ops(plan):
    """Create one completed agro-operation per resolved field (tank mix + work-type +
    driver as responsible person). Sync — call via asyncio.to_thread. Returns results."""
    wt = plan.get("work_type")
    if not wt:
        return [{"field": "—", "ok": False, "msg": "тип операции не определён"}]
    today = date.today().isoformat()
    cdt = (datetime.now() - timedelta(minutes=15)).strftime("%Y-%m-%dT%H:%M:%S")
    driver = plan.get("driver")
    # Dedup on the operation's IDENTITY (field + work-type + season), NOT a date-stamped
    # key: re-pasting the same report (even on a later day) reports «уже создано ранее»
    # instead of creating a duplicate or showing a scary «код 422». One agro-operation
    # per field × work-type × season is the CropWise model (it's how plans key, too).
    cur_year = date.today().year
    done = {(o.get("field_id"), o.get("work_type_id")) for o in _all("agro_operations")
            if o.get("season") == cur_year}
    results = []
    for f in plan["fields"]:
        if not f["field_id"]:
            results.append({"field": f["ref"], "ok": False, "msg": "поле не сопоставлено"})
            continue
        if not f.get("planned"):                 # Евгения's запрет: no план → skip, don't orphan
            results.append({"field": f["ref"], "ok": False,
                            "msg": f"вид работ «{wt['name']}» не в плане агро работ — пропущено"})
            continue
        if (f["field_id"], wt["id"]) in done:    # an op for this field+work-type already exists
            results.append({"field": f["ref"], "ok": True, "already": True,
                            "msg": "уже создано ранее"})
            continue
        area = f["area"]
        # stable (date-less) key — a re-paste yields the same key, so CropWise itself
        # also rejects a duplicate even if the scan above missed it.
        key = "flagleaf-rep-" + hashlib.sha1(
            f"{f['field_id']}|{wt['id']}|{plan['operation']}".encode()).hexdigest()[:20]
        payload = {
            "field_id": f["field_id"], "field_shape_id": f["shape"], "work_type_id": wt["id"],
            "agri_work_plan_id": f["plan_id"],   # attach to the field's план агро работ
            "idempotency_key": key,
            "status": "done", "calc_by": "rate", "completed_date": today,
            "completed_datetime": cdt, "completed_percents": 100.0,
            "planned_start_date": today, "planned_end_date": today,
        }
        if area:
            payload.update(planned_area=float(area), completed_area=float(area))
        if driver:
            payload["responsible_user_ids"] = [driver["id"]]
        mix = [_mix_item(p, area) for p in plan["products"] if p["matched"]]
        if mix:
            payload["application_mix_items"] = mix
        code, detail = create_operation(payload)
        results.append({"field": f["ref"], "ok": code in (200, 201), "code": code,
                        "detail": detail[:140]})
    return results


# ---------- machine task (logistics: КамАЗ подвоз воды — driver+machine, NO field) ----
def build_machine_task(operation, machine_raw, driver_raw, date_iso, implement_raw=None):
    """Resolve a logistics note into a CropWise machine-task plan: work_type (matched
    against ALL work types — transport isn't an agri type), machine, driver, and (for
    покос/грейдирование/…) the mounted implement. No field (one trip serves many).
    Sync — call via asyncio.to_thread."""
    # A machine task is logistics/territory work → match a NON-agri (Транспорт/…) work type,
    # never a field «Внесение/Опрыскивание» type. «подвоз воды и гербицидов» must land on
    # «Подвоз Воды+Гербициды», not «Опрыскивание и внесение гербицидов». Fall back to all
    # types only if nothing non-agri matches.
    all_wts = _all("work_types")
    wt = (match_work_type(operation, [w for w in all_wts if not w.get("agri")])
          or match_work_type(operation, all_wts))
    machine = match_machine(machine_raw, machine_raw, _all("machines")) if machine_raw else None
    implement = match_implement(implement_raw, _all("implements")) if implement_raw else None
    drivers = driver_matches(driver_raw, _all("users")) if driver_raw else []
    driver = drivers[0] if drivers else None
    return {
        "kind": "machine_task", "operation": operation, "date": date_iso,
        "work_type": {"id": wt["id"], "name": wt["name"]} if wt else None,
        "machine": {"id": machine["id"], "name": machine["name"]} if machine else None,
        "machine_raw": machine_raw,
        "implement": {"id": implement["id"], "name": implement["name"]} if implement else None,
        "implement_raw": implement_raw,
        "needs_implement": implement_needed(operation),
        "driver": {"id": driver["id"], "name": driver.get("username")} if driver else None,
        "driver_raw": driver_raw,
        # >1 only for true active full-namesakes → the bot asks which (no typeable unique id)
        "driver_options": ([{"id": u["id"], "name": u.get("username")} for u in drivers]
                           if len(drivers) > 1 else None),
    }


def mt_summary(plan):
    wt, m, d, im = plan["work_type"], plan["machine"], plan["driver"], plan.get("implement")
    lines = [
        "🚚 Задание машины (без поля) → CropWise:",
        f"Операция: {plan['operation']} → " + (f"«{wt['name']}»" if wt else "⚠️ вид работ не определён"),
        f"Машина: {plan['machine_raw'] or '—'} → " + (f"«{m['name']}»" if m else "⚠️ не найдена"),
    ]
    if im:
        lines.append(f"Оборудование: «{im['name']}»")
    elif plan.get("implement_raw"):
        lines.append(f"Оборудование: {plan['implement_raw']} → ⚠️ не найдено в CropWise")
    elif plan.get("needs_implement"):
        lines.append("Оборудование: — (без навесного)")
    lines += [
        f"Водитель: {plan['driver_raw'] or '—'} → " + (f"{d['name']}" if d else "не указан"),
        f"Дата: {date.fromisoformat(plan['date']):%d.%m.%Y}",
        "\nСоздать задание машины?",
    ]
    return "\n".join(lines)


def create_machine_task(plan):
    """POST a completed machine task to CropWise (no field). Idempotent via external_id.
    Sync — call via asyncio.to_thread. Returns (status_code, detail)."""
    wt, m, d = plan.get("work_type"), plan.get("machine"), plan.get("driver")
    if not wt:
        return 0, "вид работ не определён"
    if not m:
        return 0, "машина не найдена"
    iso = plan["date"]
    body = {
        "work_type_id": wt["id"], "machine_id": m["id"], "season": int(iso[:4]),
        "start_time": f"{iso}T08:00:00+03:00", "end_time": f"{iso}T17:00:00+03:00",
        "status": "done", "auto_created": False, "description": plan["operation"],
        "external_id": "flagleaf-mt-" + hashlib.sha1(
            f"{wt['id']}|{m['id']}|{iso}|{plan['operation']}".encode()).hexdigest()[:20],
    }
    if d:
        body["driver_id"] = d["id"]
    if plan.get("implement"):
        body["implement_id"] = plan["implement"]["id"]
    r = requests.post(f"{BASE}/machine_tasks", headers={**HEADERS, "Content-Type": "application/json"},
                      json={"data": body}, timeout=60)
    return r.status_code, r.text[:300]


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", help="report text (else read stdin)")
    ap.add_argument("--post", action="store_true", help="create in CropWise (else dry)")
    a = ap.parse_args()
    report = a.text or sys.stdin.read()
    plan, err = await build_plan(report)
    if err:
        print("✗", err, file=sys.stderr)
        return 1
    print(plan_summary(plan))
    if a.post:
        print("\n--- creating ---", file=sys.stderr)
        for r in create_ops(plan):
            print(("OK  " if r["ok"] else "FAIL") + f" поле {r['field']}: " +
                  str(r.get("detail") or r.get("msg") or r.get("code")), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
