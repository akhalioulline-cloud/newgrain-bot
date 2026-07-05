"""Person-to-person DMs: private messages between farm members (agronomist ↔ agronomist).

One flat message table; a "conversation" is just the (lesser, greater) user pair. Unread =
recipient's messages with read_at IS NULL; opening the thread marks them read. Human-only —
the bot never posts here (the bot DM stays a separate client-side chat via /api/chat).

Revision ID: 0039
Revises: 0038
Create Date: 2026-07-05
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0039"
down_revision: Union[str, None] = "0038"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS dm_messages (
            id           BIGSERIAL PRIMARY KEY,
            farm_id      INTEGER NOT NULL,
            sender_id    INTEGER NOT NULL REFERENCES users(id),
            recipient_id INTEGER NOT NULL REFERENCES users(id),
            body         TEXT NOT NULL,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            read_at      TIMESTAMPTZ
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_dm_pair ON dm_messages "
        "(LEAST(sender_id, recipient_id), GREATEST(sender_id, recipient_id), created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_dm_unread ON dm_messages (recipient_id) WHERE read_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS dm_messages")
