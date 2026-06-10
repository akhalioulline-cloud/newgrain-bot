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
