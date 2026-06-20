"""web_leads — «Связаться с агрономом» lead-capture form from ai.flagleaf.ru

Each submission is also pushed to ADMIN_TG_IDS over Telegram (best-effort); the row is the
durable record so a missed Telegram ping doesn't lose the lead.

Revision ID: 0031
Revises: 0030
Create Date: 2026-06-20
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0031"
down_revision: Union[str, None] = "0030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS web_leads (
            id         BIGSERIAL PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            name       TEXT,
            phone      TEXT,
            message    TEXT,
            ip         TEXT,
            notified   BOOLEAN NOT NULL DEFAULT false
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS web_leads")
