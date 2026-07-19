"""Shared taxonomy constants.

Disease classes for the bot's disease picker AND the annotation reference's
code resolution — one source of truth. Codes match labeling/cvat_labels.json;
Russian names match labeling/README.md. (Weeds live in the weed_species DB
table instead, with their own cvat_code column.)

When a disease class is added/removed, update this list, labeling/cvat_labels.json,
and labeling/README.md together, then run labeling.sync_labels.
"""

DISEASES = [
    ("rust_brown", "Бурая ржавчина пшеницы"),
    ("rust_yellow", "Жёлтая ржавчина"),
    ("septoria_leaf", "Септориоз листьев"),
    ("septoria_glume", "Септориоз колоса"),
    ("powdery_mildew", "Мучнистая роса"),
    ("fusarium_head", "Фузариоз колоса"),
    ("fusarium_root", "Фузариозная корневая гниль"),
    ("helminthosporium", "Гельминтоспориоз"),
    ("sunflower_phomopsis", "Фомопсис подсолнечника"),
    ("sunflower_phoma", "Фомоз подсолнечника"),
    ("sunflower_alternaria", "Альтернариоз подсолнечника"),
]

DISEASE_RU_BY_CODE = {code: ru for code, ru in DISEASES}


# Pests / insects of grain crops. Taxonomy signal (species names + Latin
# nomenclature) taken from the grain-pest atlas table of contents per
# LICENSING.md §2.1 — names only, NO atlas text/photos/recommendations used.
# (code, Russian name, Latin name, in_picker). in_picker=True is the priority
# set shown in the bot + promoted to a CVAT class now; the rest are a dictionary
# candidate pool reachable via "Другой вредитель" and promoted to a CVAT class
# on first sighting (data-driven, per labeling/schema_promotion_policy.md).
# Latin names are from the grain-pest atlas nomenclature; the CAO (Almas) can
# still adjust any if field reality differs.
PESTS = [
    ("sunn_pest",         "Клоп вредная черепашка",           "Eurygaster integriceps",            True),
    ("oulema",            "Пьявица красногрудая",             "Oulema melanopus",                  True),
    ("anisoplia",         "Хлебный жук-кузька",               "Anisoplia austriaca",               True),
    ("sitobion",          "Тля злаковая большая",             "Sitobion avenae",                   True),
    ("schizaphis",        "Тля злаковая обыкновенная",        "Schizaphis graminum",               True),
    ("rhopalosiphum",     "Тля черёмухово-злаковая",          "Rhopalosiphum padi",                True),
    ("haplothrips",       "Трипс пшеничный",                  "Haplothrips tritici",               True),
    ("oscinella_frit",    "Шведская муха овсяная",            "Oscinella frit",                    True),
    ("hessian_fly",       "Гессенская муха (комарик)",        "Mayetiola destructor",              True),
    ("delia_winter",      "Муха озимая",                      "Delia coarctata",                   True),
    ("phyllotreta",       "Блошка полосатая хлебная",         "Phyllotreta vittula",               True),
    ("cephus",            "Пилильщик хлебный обыкновенный",   "Cephus pygmaeus",                   True),
    ("agrotis_segetum",   "Совка озимая",                     "Agrotis segetum",                   True),
    ("agriotes",          "Щелкун посевной (проволочник)",    "Agriotes lineatus",                 True),
    ("zabrus",            "Жужелица хлебная обыкновенная",     "Zabrus tenebrioides",              True),
    # --- candidate pool (off-picker; via "Другой вредитель", CVAT class on first sighting) ---
    ("flea_chaetocnema",  "Блошка стеблевая хлебная большая", "Chaetocnema aridula",               False),
    ("chlorops",          "Зеленоглазка хлебная",             "Chlorops pumilionis",               False),
    ("cnephasia",         "Злаковая листовёртка",             "Cnephasia spp.",                    False),
    ("grain_mite",        "Клещ хлебный",                     "Siteroptes cerealium",              False),
    ("loxostege",         "Луговой мотылёк",                  "Loxostege sticticalis",             False),
    ("phorbia",           "Муха пшеничная чёрная",            "Phorbia fumigata",                  False),
    ("opomyza",           "Опомиза пшеничная",                "Opomyza florum",                    False),
    ("trachelus",         "Пилильщик хлебный чёрный",         "Trachelus tabidus",                 False),
    ("agrotis_excl",      "Совка восклицательная",            "Agrotis exclamationis",             False),
    ("apamea",            "Совка зерновая обыкновенная",      "Apamea anceps",                     False),
    ("spring_cutworm",    "Совка яровая",                     "Amphipoea fucosa",                  False),
    ("barley_aphid",      "Тля ячменная",                     "Diuraphis noxia",                   False),
    ("psammotettix",      "Цикадка полосатая",                "Psammotettix striatus",             False),
    ("dark_leafhopper",   "Цикадка тёмная",                   "Laodelphax striatella",             False),
    ("macrosteles",       "Цикадка шеститочечная",            "Macrosteles laevis",                False),
    ("oscinella_pusilla", "Шведская муха ячменная",           "Oscinella pusilla",                 False),
]

PESTS_PICKER = [(code, ru) for code, ru, latin, pick in PESTS if pick]
PEST_RU_BY_CODE = {code: ru for code, ru, latin, pick in PESTS}
