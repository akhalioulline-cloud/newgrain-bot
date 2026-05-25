"""seed demo farm and pilot fields (EDIT to your real farm/fields later)

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-21

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FARM_NAME = "Демо-хозяйство (замените на реальное)"


def upgrade() -> None:
    op.execute(f"INSERT INTO farms (name, region) VALUES ('{FARM_NAME}', 'ЦЧР')")
    op.execute(
        f"""
        INSERT INTO fields (farm_id, name, crop, area_ha, is_pilot, season)
        SELECT farms.id, v.name, v.crop, v.area_ha, true, 2026
        FROM farms,
             (VALUES
                ('Поле №3', 'Пшеница', 280),
                ('Поле №7', 'Подсолнечник', 410),
                ('Поле №12', 'Соя', 320)
             ) AS v(name, crop, area_ha)
        WHERE farms.name = '{FARM_NAME}'
        """
    )


def downgrade() -> None:
    op.execute(
        f"DELETE FROM fields WHERE farm_id IN (SELECT id FROM farms WHERE name = '{FARM_NAME}')"
    )
    op.execute(f"DELETE FROM farms WHERE name = '{FARM_NAME}'")
