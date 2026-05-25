"""seed weed species dictionary

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# latin_name, russian_name, is_regional_top (shown as inline keyboard buttons)
SPECIES = [
    ("Ambrosia artemisiifolia", "Амброзия полыннолистная", True),
    ("Cirsium arvense", "Осот полевой", True),
    ("Convolvulus arvensis", "Вьюнок полевой", True),
    ("Chenopodium album", "Марь белая", True),
    ("Amaranthus retroflexus", "Щирица запрокинутая", True),
    ("Helianthus annuus (volunteer)", "Падалица подсолнечника", True),
    ("Setaria viridis", "Щетинник зелёный", True),
    ("Echinochloa crus-galli", "Куриное просо", True),
    ("Sonchus arvensis", "Осот жёлтый", False),
    ("Brassica napus (volunteer)", "Падалица рапса", False),
    ("Elytrigia repens", "Пырей ползучий", False),
    ("Avena fatua", "Овсюг", False),
    ("Xanthium strumarium", "Дурнишник обыкновенный", False),
    ("Galium aparine", "Подмаренник цепкий", False),
    ("Polygonum convolvulus", "Горец вьюнковый", False),
]


def upgrade() -> None:
    table = sa.table(
        "weed_species",
        sa.column("latin_name", sa.String),
        sa.column("russian_name", sa.String),
        sa.column("is_regional_top", sa.Boolean),
    )
    op.bulk_insert(
        table,
        [
            {"latin_name": latin, "russian_name": russian, "is_regional_top": top}
            for latin, russian, top in SPECIES
        ],
    )


def downgrade() -> None:
    op.execute("DELETE FROM weed_species")
