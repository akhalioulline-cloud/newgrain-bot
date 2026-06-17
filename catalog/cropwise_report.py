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
import json
import re
import sys

import requests

from bot.config import settings
from catalog.cropwise_push import (_all, _lead_int, _match_product, _norm, _split_dose,
                                   load_catalogs)

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
    "(через пробел или дефис). Препараты — строки вида «Название - доза». Поля — строки "
    "вида «число/число» (после «Поля:» если есть). Если препаратов/полей нет — пустые "
    "списки. Отвечай только JSON."
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
def match_work_type(op_text, agri_types):
    """Best agri work_type for the report's operation line, by token overlap (+crop/pass)."""
    want = set(_norm_txt(op_text).replace("-", " ").split())
    best, score = None, 0
    for w in agri_types:
        toks = set(_norm_txt(w["name"]).replace("-", " ").split())
        s = len(want & toks)
        # bonus when the pass number matches (1/№1/1-я, 2/2-я …)
        for d in re.findall(r"\d", op_text):
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


def match_driver(surname, users):
    s = _norm_txt(surname)
    if not s:
        return None
    for u in users:
        un = _norm_txt(u.get("username"))
        if un and (un.split()[0] == s or s in un):
            return u
    return None


async def build_plan(report):
    parsed = await parse_report(report)
    if not parsed:
        return None, "не удалось разобрать отчёт"
    cat = load_catalogs()
    machines = _all("machines")
    users = _all("users")
    agri = [w for w in _all("work_types") if w.get("agri")]

    wt = match_work_type(parsed.get("operation", ""), agri)
    machine = match_machine(parsed.get("machine_number"), parsed.get("machine_type"), machines)
    driver = match_driver(parsed.get("driver"), users)

    prods = []
    for p in parsed.get("products", []):
        pm = _match_product(p.get("name", ""), cat["prods"])
        rate, unit = _split_dose(p.get("dose"))
        prods.append({"name": p.get("name"), "dose": p.get("dose"), "matched": bool(pm),
                      "applicable": pm, "rate": rate, "unit_label": unit})

    fields = []
    for f in parsed.get("fields", []):
        fid = cat["by_name"].get(_norm("Поле " + str(f))) or \
            cat["by_numarea"].get((_lead_int(str(f)),
                                   _area_of(f)))
        # fall back: try matching the leading number to a single CW field
        fields.append({"ref": f, "cw": fid})

    plan = {"parsed": parsed, "work_type": wt, "machine": machine, "driver": driver,
            "products": prods, "fields": fields}
    return plan, None


def _area_of(ref):
    m = re.search(r"/(\d+)", str(ref))
    return int(m.group(1)) if m else None


def _print_plan(plan):
    p = plan["parsed"]
    wt = plan["work_type"]
    print("Операция :", p.get("operation"),
          "→ work_type", (f"{wt['id']} «{wt['name']}»" if wt else "НЕ СОПОСТАВЛЕНО ✗"))
    m = plan["machine"]
    print("Машина   :", p.get("machine_type"), p.get("machine_number"),
          "→", (f"id {m['id']} «{m['name']}»" if m else "НЕ НАЙДЕНА ✗"))
    d = plan["driver"]
    print("Механизатор:", p.get("driver"),
          "→", (f"id {d['id']} «{d['username']}»" if d else "НЕ НАЙДЕН ✗"))
    print("Препараты:")
    for pr in plan["products"]:
        print(f"   {'✓' if pr['matched'] else '✗'} {pr['name']} {pr['dose'] or ''}"
              + ("" if pr['matched'] else "  (нет в каталоге)"))
    print("Поля:")
    for f in plan["fields"]:
        print(f"   {'✓' if f['cw'] else '✗'} {f['ref']}"
              + ("" if f['cw'] else "  (не сопоставлено)"))
    n = sum(1 for f in plan["fields"] if f["cw"])
    print(f"\nИтог: будет создано {n} агрооперац. (по одной на поле) с баковой смесью.")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", help="report text (else read stdin)")
    ap.add_argument("--post", action="store_true", help="create in CropWise (else dry preview)")
    a = ap.parse_args()
    report = a.text or sys.stdin.read()
    plan, err = await build_plan(report)
    if err:
        print("✗", err, file=sys.stderr)
        return 1
    _print_plan(plan)
    if a.post:
        print("\n[--post not implemented in stage 1 — preview only]", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
