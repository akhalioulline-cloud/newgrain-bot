"""add weed_species.cvat_code + 5 observed species + Бодяк alias

Two things:
1. cvat_code column — explicit map from a species to its CVAT label code, so
   the annotation reference sheet can tell the annotator exactly which label
   to apply (not just the Latin name). Populated for every species that has a
   CVAT label; left NULL for dictionary-only species (Stellaria, Capsella —
   not yet promoted to a CVAT class per the schema-promotion policy).
2. Five weed species Almas photographed but that weren't in the schema, now
   promoted to dictionary + CVAT class (tier 1 + tier 2 — each has ≥1 sighting):
   Euphorbia virgata, Taraxacum officinale, Artemisia vulgaris,
   Equisetum arvense, Polygonum aviculare. Plus the alias "Бодяк полевой"
   for the existing Cirsium arvense (same species as Осот полевой).

NOTE: "Молокан / молочай" submission left unresolved on purpose — ambiguous
between Lactuca tatarica (молокан) and Euphorbia (молочай); CAO to confirm.

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-10
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# latin_name → cvat label code (only species that have a CVAT class)
CODE_MAP = {
    "Ambrosia artemisiifolia": "ambrosia",
    "Cirsium arvense": "cirsium",
    "Convolvulus arvensis": "convolvulus",
    "Chenopodium album": "chenopodium",
    "Amaranthus retroflexus": "amaranthus",
    "Helianthus annuus (volunteer)": "helianthus_v",
    "Setaria viridis": "setaria",
    "Echinochloa crus-galli": "echinochloa",
    "Sonchus arvensis": "sonchus",
    "Brassica napus (volunteer)": "brassica_v",
    "Elytrigia repens": "elytrigia",
    "Avena fatua": "avena",
    "Xanthium strumarium": "xanthium",
    "Galium aparine": "galium",
    "Polygonum convolvulus": "polygonum",
    "Lathyrus tuberosus": "lathyrus_tuberosus",
    "Apera spica-venti": "apera",
    "Lamium amplexicaule": "lamium",
}

# new observed species: latin, russian, aliases[], cvat_code
NEW_SPECIES = [
    ("Euphorbia virgata", "Молочай прутьевидный", ["молочай", "Euphorbia esula"], "euphorbia"),
    ("Taraxacum officinale", "Одуванчик лекарственный", ["одуванчик"], "taraxacum"),
    ("Artemisia vulgaris", "Полынь обыкновенная", ["полынь", "чернобыльник"], "artemisia"),
    ("Equisetum arvense", "Хвощ полевой", ["хвощ"], "equisetum"),
    ("Polygonum aviculare", "Спорыш (горец птичий)", ["спорыш", "горец птичий"], "polygonum_aviculare"),
]


def _arr(items):
    inner = ", ".join("'" + i.replace("'", "''") + "'" for i in items)
    return "ARRAY[" + inner + "]::text[]"


def upgrade() -> None:
    op.execute("ALTER TABLE weed_species ADD COLUMN cvat_code VARCHAR(50)")
    for latin, code in CODE_MAP.items():
        op.execute(
            f"UPDATE weed_species SET cvat_code = '{code}' "
            f"WHERE latin_name = '{latin.replace(chr(39), chr(39)*2)}'"
        )
    # Бодяк полевой is the same species as Осот полевой (Cirsium arvense).
    op.execute(
        "UPDATE weed_species "
        "SET common_aliases = array_cat(COALESCE(common_aliases, '{}'), "
        "ARRAY['Бодяк полевой','бодяк']::text[]) "
        "WHERE latin_name = 'Cirsium arvense'"
    )
    for latin, russian, aliases, code in NEW_SPECIES:
        op.execute(
            "INSERT INTO weed_species "
            "(latin_name, russian_name, common_aliases, is_regional_top, cvat_code) "
            f"VALUES ('{latin}', '{russian}', {_arr(aliases)}, false, '{code}')"
        )


def downgrade() -> None:
    latins = ", ".join("'" + s[0] + "'" for s in NEW_SPECIES)
    op.execute(f"DELETE FROM weed_species WHERE latin_name IN ({latins})")
    op.execute(
        "UPDATE weed_species "
        "SET common_aliases = array_remove(array_remove(common_aliases, 'Бодяк полевой'), 'бодяк') "
        "WHERE latin_name = 'Cirsium arvense'"
    )
    op.execute("ALTER TABLE weed_species DROP COLUMN cvat_code")
