"""extend fields (cropwise_id, field_group) + field_crops rotation table

Whole-farm ingestion from the CropWise bulk export: ~283 fields with multi-year
crop rotation. The 3 pilot fields are matched (by number+area) and enriched, not
duplicated; the rest are added is_pilot=false. field_crops holds crop/variety/
yield per (field, year) — powers the same-crop NDVI baseline farm-wide.

Revision ID: 0016
Revises: 0015
Create Date: 2026-06-11
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE fields ADD COLUMN IF NOT EXISTS cropwise_id INTEGER")
    op.execute("ALTER TABLE fields ADD COLUMN IF NOT EXISTS field_group TEXT")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_fields_cropwise ON fields (cropwise_id) WHERE cropwise_id IS NOT NULL")
    op.execute(
        """
        CREATE TABLE field_crops (
            id           SERIAL PRIMARY KEY,
            field_id     INTEGER REFERENCES fields(id),
            year         INTEGER NOT NULL,
            crop         TEXT,
            variety      TEXT,
            sow_date     DATE,
            harvest_date DATE,
            yield_cwt    NUMERIC,   -- ц/га
            source       TEXT DEFAULT 'cropwise',
            UNIQUE (field_id, year)
        )
        """
    )
    op.execute("CREATE INDEX idx_field_crops_field ON field_crops (field_id)")
    op.execute("CREATE INDEX idx_field_crops_year ON field_crops (year, crop)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS field_crops")
    op.execute("DROP INDEX IF EXISTS idx_fields_cropwise")
    op.execute("ALTER TABLE fields DROP COLUMN IF EXISTS field_group")
    op.execute("ALTER TABLE fields DROP COLUMN IF EXISTS cropwise_id")
