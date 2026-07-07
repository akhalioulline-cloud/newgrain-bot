"""DM delivery tracking: delivered_at on dm_messages — set when the RECIPIENT's device fetches
the message (their app polled /api/chats, /api/dm/threads or the thread). Powers the tick
ladder: sent (stored) → received (their device has it) → read (they opened the thread).

Revision ID: 0044
Revises: 0043
Create Date: 2026-07-07
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0044"
down_revision: Union[str, None] = "0043"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE dm_messages ADD COLUMN IF NOT EXISTS delivered_at TIMESTAMPTZ")
    # messages already read were obviously delivered
    op.execute("UPDATE dm_messages SET delivered_at = read_at WHERE delivered_at IS NULL AND read_at IS NOT NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE dm_messages DROP COLUMN IF EXISTS delivered_at")
