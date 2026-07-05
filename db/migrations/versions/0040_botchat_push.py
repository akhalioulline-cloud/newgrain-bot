"""Bot-chat persistence + per-device push tokens.

bot_chat_messages: the «Личное» you↔Flagleaf thread moves server-side — survives app
restarts and syncs across devices (was client-only useState).
push_tokens: one row per DEVICE (not per user) so a user logged in on phone+tablet gets
notified on both; token is the Expo push token, unique — re-registering moves it to the
current user.

Revision ID: 0040
Revises: 0039
Create Date: 2026-07-05
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0040"
down_revision: Union[str, None] = "0039"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS bot_chat_messages (
            id         BIGSERIAL PRIMARY KEY,
            user_id    INTEGER NOT NULL REFERENCES users(id),
            role       TEXT NOT NULL CHECK (role IN ('user', 'bot')),
            body       TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_botchat_user ON bot_chat_messages(user_id, created_at DESC)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS push_tokens (
            token      TEXT PRIMARY KEY,
            user_id    INTEGER NOT NULL REFERENCES users(id),
            platform   TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_push_user ON push_tokens(user_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS bot_chat_messages")
    op.execute("DROP TABLE IF EXISTS push_tokens")
