"""Mode-of-Action knowledge + field-level agronomic analysis.

- MOA: active substance (Russian) -> (type, HRAC/FRAC/IRAC group, class name).
  Repeated reliance on one group builds resistance — the agronomic signal we flag.
- moa_lines(): aggregate a field's protection history by MoA group, flag overuse.
- ndvi_anomaly_lines(): flag recent weeks where NDVI dropped vs the field's own
  history for that week-of-year (heuristic; the field rotates crops, so treat as
  a screen, not a verdict).
"""
from collections import defaultdict
from statistics import mean

# Latin lookalikes seen in the source data (e.g. "ципермeтрин" has a Latin 'e')
_LAT2CYR = str.maketrans({"a": "а", "e": "е", "o": "о", "p": "р", "c": "с",
                          "x": "х", "y": "у", "k": "к", "m": "м", "t": "т", "b": "в", "h": "н"})


def _fold(s):
    return (s or "").lower().translate(_LAT2CYR)


# folded-substring key -> (type, group, class)
MOA = {
    # --- herbicides (HRAC) ---
    "2,4-д": ("гербицид", "HRAC 4", "синтетические ауксины"),
    "дикамба": ("гербицид", "HRAC 4", "синтетические ауксины"),
    "флорасулам": ("гербицид", "HRAC 2", "ALS-ингибиторы"),
    "тифенсульфурон": ("гербицид", "HRAC 2", "ALS-ингибиторы"),
    "трибенурон": ("гербицид", "HRAC 2", "ALS-ингибиторы"),
    "имазамокс": ("гербицид", "HRAC 2", "ALS-ингибиторы"),
    "имазапир": ("гербицид", "HRAC 2", "ALS-ингибиторы"),
    "имазетапир": ("гербицид", "HRAC 2", "ALS-ингибиторы"),
    "бентазон": ("гербицид", "HRAC 6", "ингибиторы ФС II"),
    "фомесафен": ("гербицид", "HRAC 14", "ингибиторы ПрО (PPO)"),
    "галоксифоп": ("гербицид", "HRAC 1", "ингибиторы АСС-азы"),
    "феноксапроп": ("гербицид", "HRAC 1", "ингибиторы АСС-азы"),
    "клодинафоп": ("гербицид", "HRAC 1", "ингибиторы АСС-азы"),
    "хизалофоп": ("гербицид", "HRAC 1", "ингибиторы АСС-азы"),
    "глифосат": ("гербицид", "HRAC 9", "ингибиторы EPSPS"),
    "кломазон": ("гербицид", "HRAC 13", "ингиб. синтеза каротиноидов"),
    "пропизохлор": ("гербицид", "HRAC 15", "ингиб. синтеза ДЦЖК (VLCFA)"),
    "тербутилазин": ("гербицид", "HRAC 5", "ингибиторы ФС II (триазины)"),
    "прометрин": ("гербицид", "HRAC 5", "ингибиторы ФС II (триазины)"),
    "дикват": ("десикант", "HRAC 22", "отвод. электронов ФС I"),
    "клоквинтосет": ("антидот", "—", "антидот (safener)"),
    # --- fungicides (FRAC) ---
    "азоксистробин": ("фунгицид", "FRAC 11", "Qo-ингибиторы (стробилурины)"),
    "пираклостробин": ("фунгицид", "FRAC 11", "Qo-ингибиторы (стробилурины)"),
    "пикоксистробин": ("фунгицид", "FRAC 11", "Qo-ингибиторы (стробилурины)"),
    "дифеноконазол": ("фунгицид", "FRAC 3", "DMI (триазолы)"),
    "пропиконазол": ("фунгицид", "FRAC 3", "DMI (триазолы)"),
    "тебуконазол": ("фунгицид", "FRAC 3", "DMI (триазолы)"),
    "эпоксиконазол": ("фунгицид", "FRAC 3", "DMI (триазолы)"),
    "протиоконазол": ("фунгицид", "FRAC 3", "DMI (триазолы)"),
    "боскалид": ("фунгицид", "FRAC 7", "SDHI"),
    "пидифлуметофен": ("фунгицид", "FRAC 7", "SDHI"),
    "карбендазим": ("фунгицид", "FRAC 1", "MBC (бензимидазолы)"),
    "спироксамин": ("фунгицид", "FRAC 5", "амины (морфолины)"),
    "фенпропиморф": ("фунгицид", "FRAC 5", "амины (морфолины)"),
    # --- insecticides (IRAC) ---
    "циперметрин": ("инсектицид", "IRAC 3A", "пиретроиды"),
    "цигалотрин": ("инсектицид", "IRAC 3A", "пиретроиды"),
    "имидаклоприд": ("инсектицид", "IRAC 4A", "неоникотиноиды"),
    "клотианидин": ("инсектицид", "IRAC 4A", "неоникотиноиды"),
    "индоксакарб": ("инсектицид", "IRAC 22A", "блокаторы Na-каналов"),
    "абамектин": ("инсектицид", "IRAC 6", "авермектины (GluCl)"),
}


def classify(active_substance):
    """Return distinct (type, group, class) MoA tuples present in the string."""
    folded = _fold(active_substance)
    out, seen = [], set()
    for key, val in MOA.items():
        if key in folded and val[1] not in seen:
            seen.add(val[1])
            out.append(val)
    return out


def moa_lines(rows, top=6):
    """rows: [(active_substance, season), …] for one field's protection history.
    Returns display lines per MoA group, sorted by use, flagging overuse."""
    agg = defaultdict(lambda: {"n": 0, "seasons": set(), "name": "", "type": ""})
    for act, season in rows:
        for typ, code, name in classify(act):
            if typ == "антидот":
                continue
            a = agg[code]
            a["n"] += 1
            a["name"], a["type"] = name, typ
            if season:
                a["seasons"].add(season)
    lines = []
    for code, a in sorted(agg.items(), key=lambda kv: -kv[1]["n"])[:top]:
        ns = len(a["seasons"])
        flag = " ⚠️ риск резистентности" if (a["n"] >= 6 or ns >= 4) else ""
        lines.append(f"  {code} · {a['name']}: {a['n']} прим., {ns} сез.{flag}")
    return lines


def ndvi_anomaly_lines(rows, top=3):
    """rows: [(week_start, week_no, ndvi), …] sorted by week_start (ndvi not null).
    Flags recent weeks notably below the field's own week-of-year norm, and sharp
    in-season drops. Heuristic (crop rotation + ripening confound)."""
    rows = [(ws, wn, float(nd)) for ws, wn, nd in rows if wn]
    if len(rows) < 20:
        return []
    by_week = defaultdict(list)
    for _ws, wn, nd in rows:
        by_week[wn].append(nd)
    base = {wn: mean(v) for wn, v in by_week.items() if len(v) >= 3}

    last = rows[-1][0]
    recent = [(ws, wn, nd) for ws, wn, nd in rows if (last - ws).days <= 250]
    found = {}
    # below the field's own norm for that week-of-year
    for ws, wn, nd in recent:
        b = base.get(wn)
        if b is not None and 14 <= wn <= 40 and nd < b - 0.12:
            found[ws] = f"  {ws:%d.%m.%Y}: NDVI {nd:.2f} — ниже нормы недели ({b:.2f})"
    # sharp in-season drop (vegetative phase, where a drop is unexpected)
    for i in range(1, len(recent)):
        ws, wn, nd = recent[i]
        prev = recent[i - 1][2]
        if 14 <= wn <= 26 and nd - prev <= -0.12:
            found[ws] = f"  {ws:%d.%m.%Y}: NDVI упал {prev:.2f}→{nd:.2f} (возможный стресс)"
    return [found[k] for k in sorted(found, reverse=True)][:top]
