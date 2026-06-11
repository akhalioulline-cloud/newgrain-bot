"""add PostGIS geometry to fields (whole-farm boundaries from the GeoJSON export)

Revision ID: 0017
Revises: 0016
Create Date: 2026-06-11
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("ALTER TABLE fields ADD COLUMN IF NOT EXISTS geom geometry(MultiPolygon, 4326)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_fields_geom ON fields USING GIST (geom)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_fields_geom")
    op.execute("ALTER TABLE fields DROP COLUMN IF EXISTS geom")
