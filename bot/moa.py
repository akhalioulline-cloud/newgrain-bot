"""Mode-of-Action knowledge + field-level agronomic analysis.

MOA maps active substances (Russian, as written in the Минсельхоз catalog) to
their HRAC / FRAC / IRAC group. Repeated reliance on one group builds resistance —
the agronomic signal we flag. Coverage is catalog-wide for the common chemistry;
agrochemicals/biostimulants/micronutrients have no pesticide MoA and stay unmapped
(classify() simply skips them). Numbering: legacy-global HRAC, numeric FRAC,
IRAC group codes.

- classify(): substances present in an active-substance string -> MoA tuples.
- moa_lines(): aggregate a field's protection history by MoA, flag overuse.
- ndvi_anomaly_samecrop(): flag recent weeks below the SAME-CROP week-of-year
  baseline (pooled across fields/years), removing the crop-rotation confound.
"""
from collections import defaultdict
from statistics import mean

# Latin lookalikes seen in the source data (e.g. "ципермeтрин" has a Latin 'e')
_LAT2CYR = str.maketrans({"a": "а", "e": "е", "o": "о", "p": "р", "c": "с",
                          "x": "х", "y": "у", "k": "к", "m": "м", "t": "т", "b": "в", "h": "н"})


def _fold(s):
    return (s or "").lower().translate(_LAT2CYR)


# folded-substring key -> (type, group, class). Keys must be specific enough to
# avoid cross-matching (use full substance stems, not shared suffixes).
MOA = {
    # ============ HERBICIDES (HRAC) ============
    # HRAC 1 — ACCase inhibitors
    "клетодим": ("гербицид", "HRAC 1", "ингибиторы АСС-азы"),
    "феноксапроп": ("гербицид", "HRAC 1", "ингибиторы АСС-азы"),
    "клодинафоп": ("гербицид", "HRAC 1", "ингибиторы АСС-азы"),
    "хизалофоп": ("гербицид", "HRAC 1", "ингибиторы АСС-азы"),
    "галоксифоп": ("гербицид", "HRAC 1", "ингибиторы АСС-азы"),
    "флуазифоп": ("гербицид", "HRAC 1", "ингибиторы АСС-азы"),
    "пропаквизафоп": ("гербицид", "HRAC 1", "ингибиторы АСС-азы"),
    "квизалофоп": ("гербицид", "HRAC 1", "ингибиторы АСС-азы"),
    "циклоксидим": ("гербицид", "HRAC 1", "ингибиторы АСС-азы"),
    "тепралоксидим": ("гербицид", "HRAC 1", "ингибиторы АСС-азы"),
    "пиноксаден": ("гербицид", "HRAC 1", "ингибиторы АСС-азы"),
    "профоксидим": ("гербицид", "HRAC 1", "ингибиторы АСС-азы"),
    # HRAC 2 — ALS inhibitors
    "трибенурон": ("гербицид", "HRAC 2", "ALS-ингибиторы"),
    "тифенсульфурон": ("гербицид", "HRAC 2", "ALS-ингибиторы"),
    "метсульфурон": ("гербицид", "HRAC 2", "ALS-ингибиторы"),
    "хлорсульфурон": ("гербицид", "HRAC 2", "ALS-ингибиторы"),
    "римсульфурон": ("гербицид", "HRAC 2", "ALS-ингибиторы"),
    "никосульфурон": ("гербицид", "HRAC 2", "ALS-ингибиторы"),
    "форамсульфурон": ("гербицид", "HRAC 2", "ALS-ингибиторы"),
    "йодосульфурон": ("гербицид", "HRAC 2", "ALS-ингибиторы"),
    "мезосульфурон": ("гербицид", "HRAC 2", "ALS-ингибиторы"),
    "амидосульфурон": ("гербицид", "HRAC 2", "ALS-ингибиторы"),
    "трифлусульфурон": ("гербицид", "HRAC 2", "ALS-ингибиторы"),
    "сульфосульфурон": ("гербицид", "HRAC 2", "ALS-ингибиторы"),
    "флупирсульфурон": ("гербицид", "HRAC 2", "ALS-ингибиторы"),
    "флорасулам": ("гербицид", "HRAC 2", "ALS-ингибиторы"),
    "пироксулам": ("гербицид", "HRAC 2", "ALS-ингибиторы"),
    "пеноксулам": ("гербицид", "HRAC 2", "ALS-ингибиторы"),
    "флукарбазон": ("гербицид", "HRAC 2", "ALS-ингибиторы"),
    "пропоксикарбазон": ("гербицид", "HRAC 2", "ALS-ингибиторы"),
    "имазамокс": ("гербицид", "HRAC 2", "ALS-ингибиторы"),
    "имазапир": ("гербицид", "HRAC 2", "ALS-ингибиторы"),
    "имазетапир": ("гербицид", "HRAC 2", "ALS-ингибиторы"),
    "имазетабенз": ("гербицид", "HRAC 2", "ALS-ингибиторы"),
    "имазаквин": ("гербицид", "HRAC 2", "ALS-ингибиторы"),
    # HRAC 3 — microtubule (dinitroanilines)
    "пендиметалин": ("гербицид", "HRAC 3", "ингиб. сборки микротрубочек"),
    "трифлуралин": ("гербицид", "HRAC 3", "ингиб. сборки микротрубочек"),
    # HRAC 4 — synthetic auxins
    "2,4-д": ("гербицид", "HRAC 4", "синтетические ауксины"),
    "дикамба": ("гербицид", "HRAC 4", "синтетические ауксины"),
    "клопиралид": ("гербицид", "HRAC 4", "синтетические ауксины"),
    "флуроксипир": ("гербицид", "HRAC 4", "синтетические ауксины"),
    "триклопир": ("гербицид", "HRAC 4", "синтетические ауксины"),
    "пиклорам": ("гербицид", "HRAC 4", "синтетические ауксины"),
    "аминопиралид": ("гербицид", "HRAC 4", "синтетические ауксины"),
    "мцпа": ("гербицид", "HRAC 4", "синтетические ауксины"),
    "2м-4х": ("гербицид", "HRAC 4", "синтетические ауксины"),
    "мекопроп": ("гербицид", "HRAC 4", "синтетические ауксины"),
    "дихлорпроп": ("гербицид", "HRAC 4", "синтетические ауксины"),
    "галауксифен": ("гербицид", "HRAC 4", "синтетические ауксины"),
    # HRAC 5 — PSII inhibitors (serine-264: triazines, ureas, etc.)
    "метрибузин": ("гербицид", "HRAC 5", "ингибиторы ФС II"),
    "прометрин": ("гербицид", "HRAC 5", "ингибиторы ФС II"),
    "тербутилазин": ("гербицид", "HRAC 5", "ингибиторы ФС II"),
    "атразин": ("гербицид", "HRAC 5", "ингибиторы ФС II"),
    "симазин": ("гербицид", "HRAC 5", "ингибиторы ФС II"),
    "метамитрон": ("гербицид", "HRAC 5", "ингибиторы ФС II"),
    "хлоридазон": ("гербицид", "HRAC 5", "ингибиторы ФС II"),
    "ленацил": ("гербицид", "HRAC 5", "ингибиторы ФС II"),
    "фенмедифам": ("гербицид", "HRAC 5", "ингибиторы ФС II"),
    "десмедифам": ("гербицид", "HRAC 5", "ингибиторы ФС II"),
    "изопротурон": ("гербицид", "HRAC 5", "ингибиторы ФС II"),
    "хлортолурон": ("гербицид", "HRAC 5", "ингибиторы ФС II"),
    "линурон": ("гербицид", "HRAC 5", "ингибиторы ФС II"),
    "тербутрин": ("гербицид", "HRAC 5", "ингибиторы ФС II"),
    # HRAC 6 — PSII inhibitors (histidine-215)
    "бентазон": ("гербицид", "HRAC 6", "ингибиторы ФС II (His-215)"),
    "бромоксинил": ("гербицид", "HRAC 6", "ингибиторы ФС II (His-215)"),
    "иоксинил": ("гербицид", "HRAC 6", "ингибиторы ФС II (His-215)"),
    # HRAC 9 / 10 — EPSPS / GS
    "глифосат": ("гербицид", "HRAC 9", "ингибиторы EPSPS"),
    "глюфосинат": ("гербицид", "HRAC 10", "ингибиторы глутаминсинтетазы"),
    # HRAC 13 / 14 / 15
    "кломазон": ("гербицид", "HRAC 13", "ингиб. синтеза каротиноидов"),
    "фомесафен": ("гербицид", "HRAC 14", "ингибиторы ПрО (PPO)"),
    "сульфентразон": ("гербицид", "HRAC 14", "ингибиторы ПрО (PPO)"),
    "флумиоксазин": ("гербицид", "HRAC 14", "ингибиторы ПрО (PPO)"),
    "оксифлуорфен": ("гербицид", "HRAC 14", "ингибиторы ПрО (PPO)"),
    "карфентразон": ("гербицид", "HRAC 14", "ингибиторы ПрО (PPO)"),
    "сафлуфенацил": ("гербицид", "HRAC 14", "ингибиторы ПрО (PPO)"),
    "оксадиазон": ("гербицид", "HRAC 14", "ингибиторы ПрО (PPO)"),
    "пропизохлор": ("гербицид", "HRAC 15", "ингиб. синтеза ДЦЖК (VLCFA)"),
    "ацетохлор": ("гербицид", "HRAC 15", "ингиб. синтеза ДЦЖК (VLCFA)"),
    "метолахлор": ("гербицид", "HRAC 15", "ингиб. синтеза ДЦЖК (VLCFA)"),
    "диметенамид": ("гербицид", "HRAC 15", "ингиб. синтеза ДЦЖК (VLCFA)"),
    "флуфенацет": ("гербицид", "HRAC 15", "ингиб. синтеза ДЦЖК (VLCFA)"),
    "пироксасульфон": ("гербицид", "HRAC 15", "ингиб. синтеза ДЦЖК (VLCFA)"),
    "петоксамид": ("гербицид", "HRAC 15", "ингиб. синтеза ДЦЖК (VLCFA)"),
    "диметахлор": ("гербицид", "HRAC 15", "ингиб. синтеза ДЦЖК (VLCFA)"),
    # HRAC 22 — PSI diverters (desiccants); HRAC 27 — HPPD
    "дикват": ("десикант", "HRAC 22", "отвод. электронов ФС I"),
    "паракват": ("гербицид", "HRAC 22", "отвод. электронов ФС I"),
    "мезотрион": ("гербицид", "HRAC 27", "ингибиторы HPPD"),
    "темботрион": ("гербицид", "HRAC 27", "ингибиторы HPPD"),
    "сулькотрион": ("гербицид", "HRAC 27", "ингибиторы HPPD"),
    "топрамезон": ("гербицид", "HRAC 27", "ингибиторы HPPD"),
    "изоксафлутол": ("гербицид", "HRAC 27", "ингибиторы HPPD"),
    # safeners (not a weed MoA)
    "клоквинтосет": ("антидот", "—", "антидот (safener)"),
    "мефенпир": ("антидот", "—", "антидот (safener)"),
    "изоксадифен": ("антидот", "—", "антидот (safener)"),

    # ============ FUNGICIDES (FRAC) ============
    # FRAC 3 — DMI (azoles)
    "тебуконазол": ("фунгицид", "FRAC 3", "DMI (триазолы)"),
    "пропиконазол": ("фунгицид", "FRAC 3", "DMI (триазолы)"),
    "дифеноконазол": ("фунгицид", "FRAC 3", "DMI (триазолы)"),
    "ципроконазол": ("фунгицид", "FRAC 3", "DMI (триазолы)"),
    "протиоконазол": ("фунгицид", "FRAC 3", "DMI (триазолы)"),
    "эпоксиконазол": ("фунгицид", "FRAC 3", "DMI (триазолы)"),
    "флутриафол": ("фунгицид", "FRAC 3", "DMI (триазолы)"),
    "метконазол": ("фунгицид", "FRAC 3", "DMI (триазолы)"),
    "тетраконазол": ("фунгицид", "FRAC 3", "DMI (триазолы)"),
    "пенконазол": ("фунгицид", "FRAC 3", "DMI (триазолы)"),
    "триадименол": ("фунгицид", "FRAC 3", "DMI (триазолы)"),
    "триадимефон": ("фунгицид", "FRAC 3", "DMI (триазолы)"),
    "фенбуконазол": ("фунгицид", "FRAC 3", "DMI (триазолы)"),
    "флуквинконазол": ("фунгицид", "FRAC 3", "DMI (триазолы)"),
    "ипконазол": ("фунгицид", "FRAC 3", "DMI (триазолы)"),
    "мефентрифлуконазол": ("фунгицид", "FRAC 3", "DMI (триазолы)"),
    "прохлораз": ("фунгицид", "FRAC 3", "DMI (имидазолы)"),
    "имазалил": ("фунгицид", "FRAC 3", "DMI (имидазолы)"),
    "дифеноконазол": ("фунгицид", "FRAC 3", "DMI (триазолы)"),
    # FRAC 11 — QoI (strobilurins)
    "азоксистробин": ("фунгицид", "FRAC 11", "Qo-ингибиторы (стробилурины)"),
    "пираклостробин": ("фунгицид", "FRAC 11", "Qo-ингибиторы (стробилурины)"),
    "трифлоксистробин": ("фунгицид", "FRAC 11", "Qo-ингибиторы (стробилурины)"),
    "крезоксим": ("фунгицид", "FRAC 11", "Qo-ингибиторы (стробилурины)"),
    "пикоксистробин": ("фунгицид", "FRAC 11", "Qo-ингибиторы (стробилурины)"),
    "флуоксастробин": ("фунгицид", "FRAC 11", "Qo-ингибиторы (стробилурины)"),
    "димоксистробин": ("фунгицид", "FRAC 11", "Qo-ингибиторы (стробилурины)"),
    "фамоксадон": ("фунгицид", "FRAC 11", "Qo-ингибиторы"),
    "фенамидон": ("фунгицид", "FRAC 11", "Qo-ингибиторы"),
    # FRAC 7 — SDHI
    "боскалид": ("фунгицид", "FRAC 7", "SDHI"),
    "флуопирам": ("фунгицид", "FRAC 7", "SDHI"),
    "флуксапироксад": ("фунгицид", "FRAC 7", "SDHI"),
    "бензовиндифлупир": ("фунгицид", "FRAC 7", "SDHI"),
    "пидифлуметофен": ("фунгицид", "FRAC 7", "SDHI"),
    "изопиразам": ("фунгицид", "FRAC 7", "SDHI"),
    "седаксан": ("фунгицид", "FRAC 7", "SDHI"),
    "пенфлуфен": ("фунгицид", "FRAC 7", "SDHI"),
    "биксафен": ("фунгицид", "FRAC 7", "SDHI"),
    "карбоксин": ("фунгицид", "FRAC 7", "SDHI"),
    "флутоланил": ("фунгицид", "FRAC 7", "SDHI"),
    # FRAC 1 / 9 / 12 / 5
    "карбендазим": ("фунгицид", "FRAC 1", "MBC (бензимидазолы)"),
    "тиофанат": ("фунгицид", "FRAC 1", "MBC (бензимидазолы)"),
    "беномил": ("фунгицид", "FRAC 1", "MBC (бензимидазолы)"),
    "тиабендазол": ("фунгицид", "FRAC 1", "MBC (бензимидазолы)"),
    "ципродинил": ("фунгицид", "FRAC 9", "анилинопиримидины"),
    "пириметанил": ("фунгицид", "FRAC 9", "анилинопиримидины"),
    "мепанипирим": ("фунгицид", "FRAC 9", "анилинопиримидины"),
    "флудиоксонил": ("фунгицид", "FRAC 12", "фенилпирролы"),
    "спироксамин": ("фунгицид", "FRAC 5", "амины (морфолины)"),
    "фенпропиморф": ("фунгицид", "FRAC 5", "амины (морфолины)"),
    "фенпропидин": ("фунгицид", "FRAC 5", "амины (морфолины)"),
    # FRAC 4 / 40 / 27 / 28 / 29 / 21 / 33
    "металаксил": ("фунгицид", "FRAC 4", "фениламиды (PA)"),
    "мефеноксам": ("фунгицид", "FRAC 4", "фениламиды (PA)"),
    "беналаксил": ("фунгицид", "FRAC 4", "фениламиды (PA)"),
    "диметоморф": ("фунгицид", "FRAC 40", "CAA"),
    "мандипропамид": ("фунгицид", "FRAC 40", "CAA"),
    "ипроваликарб": ("фунгицид", "FRAC 40", "CAA"),
    "бентиаваликарб": ("фунгицид", "FRAC 40", "CAA"),
    "цимоксанил": ("фунгицид", "FRAC 27", "цианоацетамид-оксимы"),
    "пропамокарб": ("фунгицид", "FRAC 28", "карбаматы"),
    "флуазинам": ("фунгицид", "FRAC 29", "разобщители"),
    "циазофамид": ("фунгицид", "FRAC 21", "QiI"),
    "амисульбром": ("фунгицид", "FRAC 21", "QiI"),
    "фосэтил": ("фунгицид", "FRAC P07", "фосфонаты"),
    "флуопиколид": ("фунгицид", "FRAC 43", "бензамиды"),
    "фенгексамид": ("фунгицид", "FRAC 17", "KRI (гидроксианилиды)"),
    "квиноксифен": ("фунгицид", "FRAC 13", "сигнальная трансдукция"),
    # FRAC multisite
    "манкоцеб": ("фунгицид", "FRAC M3", "дитиокарбаматы (мультисайт)"),
    "хлороталонил": ("фунгицид", "FRAC M5", "хлоронитрилы (мультисайт)"),
    "каптан": ("фунгицид", "FRAC M4", "фталимиды (мультисайт)"),
    "фолпет": ("фунгицид", "FRAC M4", "фталимиды (мультисайт)"),

    # ============ INSECTICIDES / ACARICIDES (IRAC) ============
    # IRAC 3A — pyrethroids
    "циперметрин": ("инсектицид", "IRAC 3A", "пиретроиды"),
    "цигалотрин": ("инсектицид", "IRAC 3A", "пиретроиды"),
    "дельтаметрин": ("инсектицид", "IRAC 3A", "пиретроиды"),
    "эсфенвалерат": ("инсектицид", "IRAC 3A", "пиретроиды"),
    "фенвалерат": ("инсектицид", "IRAC 3A", "пиретроиды"),
    "бифентрин": ("инсектицид", "IRAC 3A", "пиретроиды"),
    "перметрин": ("инсектицид", "IRAC 3A", "пиретроиды"),
    "тау-флювалинат": ("инсектицид", "IRAC 3A", "пиретроиды"),
    "тефлутрин": ("инсектицид", "IRAC 3A", "пиретроиды"),
    # IRAC 4A — neonicotinoids
    "имидаклоприд": ("инсектицид", "IRAC 4A", "неоникотиноиды"),
    "тиаметоксам": ("инсектицид", "IRAC 4A", "неоникотиноиды"),
    "клотианидин": ("инсектицид", "IRAC 4A", "неоникотиноиды"),
    "ацетамиприд": ("инсектицид", "IRAC 4A", "неоникотиноиды"),
    "тиаклоприд": ("инсектицид", "IRAC 4A", "неоникотиноиды"),
    "динотефуран": ("инсектицид", "IRAC 4A", "неоникотиноиды"),
    # IRAC 1B — organophosphates; 1A — carbamates
    "диметоат": ("инсектицид", "IRAC 1B", "фосфорорганические"),
    "хлорпирифос": ("инсектицид", "IRAC 1B", "фосфорорганические"),
    "малатион": ("инсектицид", "IRAC 1B", "фосфорорганические"),
    "диазинон": ("инсектицид", "IRAC 1B", "фосфорорганические"),
    "пиримифос": ("инсектицид", "IRAC 1B", "фосфорорганические"),
    "фозалон": ("инсектицид", "IRAC 1B", "фосфорорганические"),
    "пиримикарб": ("инсектицид", "IRAC 1A", "карбаматы"),
    "метомил": ("инсектицид", "IRAC 1A", "карбаматы"),
    # IRAC 5 / 6 / 28 / 22 / 23 / 15 / 21 / 13 / 29
    "спиносад": ("инсектицид", "IRAC 5", "спинозины"),
    "спинеторам": ("инсектицид", "IRAC 5", "спинозины"),
    "абамектин": ("инсектицид", "IRAC 6", "авермектины (GluCl)"),
    "эмамектин": ("инсектицид", "IRAC 6", "авермектины (GluCl)"),
    "хлорантранилипрол": ("инсектицид", "IRAC 28", "диамиды (рианодин)"),
    "циантранилипрол": ("инсектицид", "IRAC 28", "диамиды (рианодин)"),
    "флубендиамид": ("инсектицид", "IRAC 28", "диамиды (рианодин)"),
    "индоксакарб": ("инсектицид", "IRAC 22A", "блокаторы Na-каналов"),
    "метафлумизон": ("инсектицид", "IRAC 22B", "блокаторы Na-каналов"),
    "спиротетрамат": ("инсектицид", "IRAC 23", "ингиб. синтеза липидов"),
    "спиромесифен": ("акарицид", "IRAC 23", "ингиб. синтеза липидов"),
    "спиродиклофен": ("акарицид", "IRAC 23", "ингиб. синтеза липидов"),
    "дифлубензурон": ("инсектицид", "IRAC 15", "ингиб. синтеза хитина"),
    "люфенурон": ("инсектицид", "IRAC 15", "ингиб. синтеза хитина"),
    "новалурон": ("инсектицид", "IRAC 15", "ингиб. синтеза хитина"),
    "пирипроксифен": ("инсектицид", "IRAC 7C", "аналоги ювен. гормона"),
    "пиридабен": ("акарицид", "IRAC 21A", "METI-акарициды"),
    "фенпироксимат": ("акарицид", "IRAC 21A", "METI-акарициды"),
    "тебуфенпирад": ("акарицид", "IRAC 21A", "METI-акарициды"),
    "хлорфенапир": ("инсектицид", "IRAC 13", "разобщители (протонофоры)"),
    "флоникамид": ("инсектицид", "IRAC 29", "модуляторы хордотон. органов"),
    "пиметрозин": ("инсектицид", "IRAC 9B", "модуляторы хордотон. органов"),
    "сульфоксафлор": ("инсектицид", "IRAC 4C", "сульфоксимины"),
    "флупирадифурон": ("инсектицид", "IRAC 4D", "бутенолиды"),
    "фипронил": ("инсектицид", "IRAC 2B", "блокаторы ГАМК-каналов"),
    "клофентезин": ("акарицид", "IRAC 10A", "ингиб. роста клещей"),
    "гекситиазокс": ("акарицид", "IRAC 10A", "ингиб. роста клещей"),
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


def ndvi_anomaly_samecrop(target_fid, crop_map, ndvi_rows, top=3):
    """Flag recent weeks of the target field below the SAME-CROP week-of-year
    baseline, pooled across all fields/years to beat data scarcity.
      crop_map: {(field_id, year): crop}
      ndvi_rows: [(field_id, week_start, week_no, ndvi), …] (ndvi not null)
    Returns (lines, note). note states the baseline basis (or that history is
    insufficient for the current crop)."""
    rows_t = [(ws, wn, float(nd)) for (f, ws, wn, nd) in ndvi_rows if f == target_fid and wn]
    if not rows_t:
        return [], ""
    cur_year = max(ws.year for ws, _, _ in rows_t)
    cur_crop = crop_map.get((target_fid, cur_year))
    if not cur_crop:
        return [], ""

    base, fy = defaultdict(list), set()
    for f, ws, wn, nd in ndvi_rows:
        if not wn:
            continue
        if crop_map.get((f, ws.year)) == cur_crop and not (f == target_fid and ws.year == cur_year):
            base[wn].append(float(nd))
            fy.add((f, ws.year))
    baseln = {wn: mean(v) for wn, v in base.items() if len(v) >= 2}
    if not baseln:
        return [], f"нет истории по культуре «{cur_crop}» для сравнения"

    note = f"база: «{cur_crop}», {len(fy)} полей-лет"
    cur_weeks = sorted([(ws, wn, nd) for ws, wn, nd in rows_t if ws.year == cur_year])
    found = {}
    for ws, wn, nd in cur_weeks:
        b = baseln.get(wn)
        if b is not None and 14 <= wn <= 40 and nd < b - 0.12:
            found[ws] = f"  {ws:%d.%m.%Y}: NDVI {nd:.2f} — ниже нормы по культуре ({b:.2f})"
    for i in range(1, len(cur_weeks)):
        ws, wn, nd = cur_weeks[i]
        prev = cur_weeks[i - 1][2]
        if 14 <= wn <= 26 and nd - prev <= -0.12:
            found[ws] = f"  {ws:%d.%m.%Y}: NDVI упал {prev:.2f}→{nd:.2f} (возможный стресс)"
    return [found[k] for k in sorted(found, reverse=True)][:top], note


def ndvi_anomalies_all(field_ids, crop_map, ndvi_rows, top=3):
    """Batch version of ndvi_anomaly_samecrop for scanning many fields at once.
    Precomputes the same-crop week-of-year baseline ONCE (pooled across all
    fields/years) instead of rebuilding it per field — O(rows) total, not
    O(rows × fields). Returns {field_id: (lines, note)} for evaluated fields.
    (Unlike the single-field version it doesn't exclude the target field's own
    current year from its baseline — negligible with 100+ pooled field-years.)"""
    by_field = defaultdict(list)                       # fid -> [(ws, wn, nd)]
    base = defaultdict(lambda: defaultdict(list))      # crop -> wn -> [nd]
    for f, ws, wn, nd in ndvi_rows:
        if not wn:
            continue
        nd = float(nd)
        by_field[f].append((ws, wn, nd))
        crop = crop_map.get((f, ws.year))
        if crop:
            base[crop][wn].append(nd)
    baseln = {crop: {wn: mean(v) for wn, v in wks.items() if len(v) >= 2}
              for crop, wks in base.items()}

    out = {}
    for fid in field_ids:
        rows_t = by_field.get(fid)
        if not rows_t:
            continue
        cur_year = max(ws.year for ws, _, _ in rows_t)
        cur_crop = crop_map.get((fid, cur_year))
        if not cur_crop:
            continue
        cb = baseln.get(cur_crop)
        if not cb:
            out[fid] = ([], f"нет истории по культуре «{cur_crop}» для сравнения")
            continue
        cur_weeks = sorted([(ws, wn, nd) for ws, wn, nd in rows_t if ws.year == cur_year])
        found = {}
        for ws, wn, nd in cur_weeks:
            b = cb.get(wn)
            if b is not None and 14 <= wn <= 40 and nd < b - 0.12:
                found[ws] = f"  {ws:%d.%m.%Y}: NDVI {nd:.2f} — ниже нормы по культуре ({b:.2f})"
        for i in range(1, len(cur_weeks)):
            ws, wn, nd = cur_weeks[i]
            prev = cur_weeks[i - 1][2]
            if 14 <= wn <= 26 and nd - prev <= -0.12:
                found[ws] = f"  {ws:%d.%m.%Y}: NDVI упал {prev:.2f}→{nd:.2f} (возможный стресс)"
        out[fid] = ([found[k] for k in sorted(found, reverse=True)][:top],
                    f"база: «{cur_crop}»")
    return out
