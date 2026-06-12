"""expand the pilot: 9 more fields (3 junior agronomists × 3 fields)

Three junior agronomists join the pilot, each responsible for a Соя / Озимая
пшеница / Подсолнечник field. Per the founder's choice the picker shows all
pilot fields to everyone (responsibility is organizational — see
docs/pilot-agronomists.md), so we just flip is_pilot on the 9 fields. They were
loaded by the whole-farm bulk export and are named 'Поле <номер> · <группа>';
each номер below is unique, so matching by номер targets exactly one field.

Revision ID: 0020
Revises: 0019
Create Date: 2026-06-12
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# номер of each newly-assigned pilot field (Костенников / Швец-Ковган / Сорока)
_NUMS = ("119", "49", "170", "268", "10", "144", "39", "32", "217")
_IN = ", ".join(f"'{n}'" for n in _NUMS)
_NUMEXPR = r"btrim(regexp_replace(split_part(name, ' · ', 1), '^Поле\s+', ''))"


def upgrade() -> None:
    op.execute(f"UPDATE fields SET is_pilot = true WHERE {_NUMEXPR} IN ({_IN})")


def downgrade() -> None:
    op.execute(f"UPDATE fields SET is_pilot = false WHERE {_NUMEXPR} IN ({_IN})")
