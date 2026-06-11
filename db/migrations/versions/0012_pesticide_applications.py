"""create pesticide_applications — Минсельхоз Госкаталог ingestion

The neutral, legal recommendation source-of-truth (per LICENSING.md §3): the
state catalog of pesticides/agrochemicals registered in the RF, from the
Минсельхоз open-data portal (opendata.mcx.ru). One row per product × crop ×
target application record (denormalized) so the future agent can answer
"for <crop> + <target>, which registered products at what rate?".

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-11
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE pesticide_applications (
            id                  SERIAL PRIMARY KEY,
            product_name        TEXT NOT NULL,
            category            TEXT,   -- Гербицид / Фунгицид / Инсектицид / …
            formulation         TEXT,
            active_substances   TEXT,   -- "Прометрин (500 Грамм); …"
            registrant          TEXT,
            hazard_class        TEXT,
            reg_number          TEXT,
            reg_valid_until     DATE,
            status              TEXT,   -- Действует / …
            crop                TEXT,   -- Kultura_obrabatyvaemyy_obekt
            target              TEXT,   -- Vrednyy_obekt_naznachenie
            rate                TEXT,   -- Norma_primeneniya + unit
            application_method  TEXT,
            notes               TEXT,   -- Osobennosti_primeneniya
            avia_allowed        TEXT,
            waiting_period_freq TEXT,
            source              VARCHAR(40) DEFAULT 'goskatalog',
            ingested_at         TIMESTAMP DEFAULT now()
        )
        -- (registry text varies widely; TEXT avoids length-truncation surprises)
        """
    )
    op.execute("CREATE INDEX idx_pest_crop ON pesticide_applications (crop)")
    op.execute("CREATE INDEX idx_pest_category ON pesticide_applications (category)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS pesticide_applications")
