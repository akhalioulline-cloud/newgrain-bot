"""create field_treatments — digitized field operation / treatment history

The agent's field-context layer: what was applied to each field, when, at what
dose, against what, and with what result. Source is the farm's own records
(CropWise export / 1C / manual) — the farm's data, not third-party IP. Soft-links
to pesticide_applications by product name (no FK — the catalog reloads).

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-11
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE field_treatments (
            id               SERIAL PRIMARY KEY,
            field_id         INTEGER REFERENCES fields(id),  -- matched from field_name; NULL if no match
            field_name       TEXT,            -- as given in the source
            treatment_date   DATE,
            season           INTEGER,         -- year (derived from date if blank)
            crop             TEXT,            -- crop growing at the time
            operation        TEXT,            -- опрыскивание / внесение / обработка семян / …
            product          TEXT,            -- trade name (↔ pesticide_applications.product_name)
            active_substance TEXT,
            target           TEXT,            -- weed / disease / pest treated
            dose             TEXT,            -- e.g. "1,5 л/га"
            area_ha          NUMERIC(10,2),
            phenophase       TEXT,            -- crop stage at treatment
            conditions       TEXT,            -- weather / conditions
            cost             TEXT,
            result           TEXT,            -- observed efficacy / outcome
            operator         TEXT,            -- who performed it
            source           TEXT DEFAULT 'manual',  -- cropwise / 1c / manual
            note             TEXT,
            created_at       TIMESTAMP DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX idx_treat_field ON field_treatments (field_id)")
    op.execute("CREATE INDEX idx_treat_date ON field_treatments (treatment_date)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS field_treatments")
