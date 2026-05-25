"""swap demo farm/fields for the real New Grain Co pilot fields

Non-destructive: the demo farm row is renamed in place (so existing user
links survive) and the demo fields are hidden from the pilot list rather than
deleted (so test submissions referencing them stay intact). The three real
pilot fields are added.

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-25

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEMO_FARM_NAME = "Демо-хозяйство (замените на реальное)"
REAL_FARM_NAME = "New Grain Co"
DEMO_FIELDS = ("Поле №3", "Поле №7", "Поле №12")


def upgrade() -> None:
    # 1. Rename the demo farm in place (keeps users.farm_id links valid).
    op.execute(
        f"UPDATE farms SET name = '{REAL_FARM_NAME}' WHERE name = '{DEMO_FARM_NAME}'"
    )

    # 2. Hide the old demo fields from the pilot (keep rows + their submissions).
    demo_list = ", ".join(f"'{n}'" for n in DEMO_FIELDS)
    op.execute(
        f"""
        UPDATE fields SET is_pilot = false
        WHERE name IN ({demo_list})
          AND farm_id IN (SELECT id FROM farms WHERE name = '{REAL_FARM_NAME}')
        """
    )

    # 3. Add the real pilot fields.
    op.execute(
        f"""
        INSERT INTO fields (farm_id, name, crop, area_ha, is_pilot, season)
        SELECT farms.id, v.name, v.crop, v.area_ha, true, 2026
        FROM farms,
             (VALUES
                ('Поле 121/140', 'Соя', 140),
                ('Поле 171/99', 'Подсолнечник', 99),
                ('Поле 76/108', 'Пшеница', 108)
             ) AS v(name, crop, area_ha)
        WHERE farms.name = '{REAL_FARM_NAME}'
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        DELETE FROM fields
        WHERE name IN ('Поле 121/140', 'Поле 171/99', 'Поле 76/108')
          AND farm_id IN (SELECT id FROM farms WHERE name = '{REAL_FARM_NAME}')
        """
    )
    demo_list = ", ".join(f"'{n}'" for n in DEMO_FIELDS)
    op.execute(
        f"""
        UPDATE fields SET is_pilot = true
        WHERE name IN ({demo_list})
          AND farm_id IN (SELECT id FROM farms WHERE name = '{REAL_FARM_NAME}')
        """
    )
    op.execute(
        f"UPDATE farms SET name = '{DEMO_FARM_NAME}' WHERE name = '{REAL_FARM_NAME}'"
    )
