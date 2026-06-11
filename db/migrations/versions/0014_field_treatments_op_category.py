"""add op_category to field_treatments (CropWise operation sections)

CropWise operations come in sections — tillage / sowing / fertilizer / protection
(СЗР). op_category lets the agent filter (e.g. only plant-protection history).

Revision ID: 0014
Revises: 0013
Create Date: 2026-06-11
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE field_treatments ADD COLUMN op_category TEXT")
    op.execute("CREATE INDEX idx_treat_category ON field_treatments (op_category)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_treat_category")
    op.execute("ALTER TABLE field_treatments DROP COLUMN IF EXISTS op_category")
