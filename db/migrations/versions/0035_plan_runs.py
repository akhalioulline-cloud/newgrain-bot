"""plan_runs — savings-log: one row per generated field plan (the loop, tracked over time)

Each /plan (bot or app) records the field, the blanket-spray baseline it was measured against
(passes + ₽), and the plan text. An admin can later annotate the realized `outcome` once the loop
closes (agronomist applied the targeted plan vs the blanket) — turning it into a savings record.

Revision ID: 0035
Revises: 0034
Create Date: 2026-06-23
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0035"
down_revision: Union[str, None] = "0034"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS plan_runs (
            id              BIGSERIAL PRIMARY KEY,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            field_id        INTEGER,
            field_name      TEXT,
            season          INTEGER,
            baseline_passes INTEGER,
            baseline_cost   NUMERIC(12,2),
            plan_text       TEXT,
            outcome         TEXT,
            ran_by          BIGINT
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS plan_runs_field ON plan_runs (field_id, created_at DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS plan_runs")
