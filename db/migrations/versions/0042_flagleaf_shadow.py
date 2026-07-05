"""Flagleaf proactive SHADOW mode log: what the bot WOULD have said unsummoned (not posted).

For evaluating whether Flagleaf should become an active, self-initiating participant before it
ever speaks unprompted to the team. Each row = one message where the bot judged it could add a
short grounded fact; we read these to measure hit-rate/quality, then decide.

Revision ID: 0042
Revises: 0041
Create Date: 2026-07-05
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0042"
down_revision: Union[str, None] = "0041"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS flagleaf_shadow (
            id           BIGSERIAL PRIMARY KEY,
            farm_id      INTEGER,
            message_id   BIGINT,
            trigger_text TEXT,
            confidence   REAL,
            line         TEXT,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_shadow_farm ON flagleaf_shadow(farm_id, created_at DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS flagleaf_shadow")
