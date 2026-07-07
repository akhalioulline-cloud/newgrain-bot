"""Wall read-state: per-user last-seen wall message — powers the unread badge/bold on the
chat list (syncs across devices, like Telegram). Opening the wall marks it seen.

Revision ID: 0043
Revises: 0042
Create Date: 2026-07-07
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0043"
down_revision: Union[str, None] = "0042"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS wall_reads (
            user_id      INTEGER PRIMARY KEY REFERENCES users(id),
            last_seen_id BIGINT NOT NULL DEFAULT 0,
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS wall_reads")
