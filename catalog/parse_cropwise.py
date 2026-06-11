"""Parse a CropWise field 'multiprotocol' .xlsx export into a normalized CSV
that catalog/ingest_treatments.py can load into field_treatments.

CropWise exports one sheet per year ('Технические операции YYYY'), each split
into sections: Обработка почвы (tillage) / Сев (sowing) / Внесение удобрений
(fertilizer) / Внесение СЗР (plant protection). We read each section
header-driven (robust to column order) and emit one normalized row per operation.

Runs LOCALLY (needs openpyxl); produces a ';'-delimited CSV. Then load with
ingest_treatments.py on the server.

Usage: python catalog/parse_cropwise.py <multiprotocol.xlsx> <out.csv> --field "Поле 76/108"
"""
import argparse
import csv
import re
import sys

import openpyxl

MONTHS = {"января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6,
          "июля": 7, "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12}
SECTIONS = {  # section header label -> (category, material-column candidates)
    "Обработка почвы": ("tillage", []),
    "Сев": ("sowing", ["Семена"]),
    "Внесение удобрений": ("fertilizer", ["Удобрение"]),
    "Внесение СЗР": ("protection", ["СЗР"]),
}
OUT_COLS = ["поле", "дата", "культура", "операция", "категория", "препарат",
            "норма", "площадь_га", "примечание"]


def _round(s):
    try:
        return "%g" % round(float(str(s).replace(",", ".")), 3)
    except (ValueError, TypeError):
        return str(s or "").strip()


def _ru_date(s):
    # "05 мая 2022, 13:00" -> "05.05.2022"
    m = re.match(r"\s*(\d{1,2})\s+([а-яё]+)\s+(\d{4})", str(s or ""), re.I)
    if not m:
        return ""
    d, mon, y = m.group(1), m.group(2).lower(), m.group(3)
    mn = MONTHS.get(mon)
    return f"{int(d):02d}.{mn:02d}.{y}" if mn else ""


def _crop(op_name, sheet_default):
    t = (op_name or "").lower()
    if "сои" in t or "сою" in t or " соя" in t or t.startswith("соя"):
        return "Соя"
    if "подсолнеч" in t:
        return "Подсолнечник"
    if "озим" in t and "пшениц" in t:
        return "Озимая пшеница"
    if "яров" in t and "пшениц" in t:
        return "Яровая пшеница"
    if "пшениц" in t:
        return "Пшеница"
    return sheet_default


def _sheet_default_crop(ops):
    blob = " ".join(ops).lower()
    for key, crop in [("сои", "Соя"), ("сою", "Соя"), ("подсолнеч", "Подсолнечник"),
                      ("озим", "Озимая пшеница"), ("яров", "Яровая пшеница"), ("пшениц", "Пшеница")]:
        if key in blob:
            return crop
    return ""


def parse(path, field_name):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    out = []
    for sh in wb.sheetnames:
        if not sh.startswith("Технические операции"):
            continue
        rows = [list(r) for r in wb[sh].iter_rows(values_only=True)]
        # first pass: collect operation names to infer the sheet's dominant crop
        op_names = [str(r[2]) for r in rows if len(r) > 2 and r[2] and r[0] not in (None, "№")]
        sheet_crop = _sheet_default_crop(op_names)

        section = None
        hdr = {}
        for r in rows:
            c0 = (str(r[0]).strip() if r and r[0] is not None else "")
            if c0 in SECTIONS:
                section, hdr = c0, {}
                continue
            if c0 == "№":  # header row -> map column name -> index
                hdr = {str(c).strip(): i for i, c in enumerate(r) if c}
                continue
            if not section or not c0.isdigit() or not hdr:
                continue

            def cell(name):
                i = hdr.get(name)
                return r[i] if i is not None and i < len(r) and r[i] is not None else ""

            cat, mat_cols = SECTIONS[section]
            date = _ru_date(cell("Date"))
            op = str(cell("Название технической операции")).strip()
            product = ""
            for mc in mat_cols:
                if cell(mc):
                    product = str(cell(mc)).strip(); break
            rate = _round(cell("Норма (факт)"))
            unit = str(cell("Единицы")).strip()
            total = _round(cell("Всего (факт)"))
            area = str(cell("Площадь, га")).strip()
            depth = str(cell("Глубина")).strip()
            norma = f"{rate} {unit}".strip() if rate else ""
            note_bits = []
            if total:
                note_bits.append(f"всего {total}{(' ' + unit) if unit else ''}")
            if depth:
                note_bits.append(f"глубина {depth}")
            out.append({
                "поле": field_name,
                "дата": date,
                "культура": _crop(op, sheet_crop),
                "операция": op,
                "категория": cat,
                "препарат": product,
                "норма": norma,
                "площадь_га": area,
                "примечание": "; ".join(note_bits),
            })
    wb.close()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("xlsx")
    ap.add_argument("out_csv")
    ap.add_argument("--field", default="Поле 76/108")
    args = ap.parse_args()
    rows = parse(args.xlsx, args.field)
    rows = [r for r in rows if r["дата"]]  # drop rows we couldn't date
    with open(args.out_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OUT_COLS, delimiter=";")
        w.writeheader()
        w.writerows(rows)
    cats = {}
    for r in rows:
        cats[r["категория"]] = cats.get(r["категория"], 0) + 1
    print(f"wrote {len(rows)} ops -> {args.out_csv}", file=sys.stderr)
    print(f"by category: {cats}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
