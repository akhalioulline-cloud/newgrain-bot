"""species seed updates: setaria regional alias + 4 CBE-common species

Triggered by Almas's first batch (29 May 2026):
- "Мышей зелёный" — same species as Setaria viridis; just southern Russian
  terminology vs the northern "Щетинник зелёный" we had seeded. Match the
  Syngenta atlas convention of showing both names.
- "Чина клубненосная" (Lathyrus tuberosus) — genuine miss; add to species
  table. Stays out of the regional-top-8 inline keyboard for now; selectable
  via the new "Другой" free-text path. Promotes to top-8 only if it becomes
  frequent in agronomist submissions (see labeling/schema_promotion_policy.md).

Three other CBE-common species added at the same time because the
class-gaps memo flagged them as likely-observed but absent from the seed:
Stellaria media, Capsella bursa-pastoris, Apera spica-venti.

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-29
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Setaria: show both regional names.
    op.execute(
        "UPDATE weed_species "
        "SET russian_name = 'Щетинник зелёный / Мышей зелёный' "
        "WHERE latin_name = 'Setaria viridis'"
    )

    # 2. Add four CBE-common species, all non-regional-top
    #    (inline keyboard stays at 8 buttons; these reach the agronomist
    #    via the new /Другой free-text path).
    op.execute(
        """
        INSERT INTO weed_species (latin_name, russian_name, is_regional_top)
        VALUES
            ('Lathyrus tuberosus', 'Чина клубненосная', false),
            ('Stellaria media', 'Звездчатка средняя (мокрица)', false),
            ('Capsella bursa-pastoris', 'Пастушья сумка', false),
            ('Apera spica-venti', 'Метлица обыкновенная', false)
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM weed_species WHERE latin_name IN ("
        "'Lathyrus tuberosus', 'Stellaria media', "
        "'Capsella bursa-pastoris', 'Apera spica-venti')"
    )
    op.execute(
        "UPDATE weed_species "
        "SET russian_name = 'Щетинник зелёный' "
        "WHERE latin_name = 'Setaria viridis'"
    )
