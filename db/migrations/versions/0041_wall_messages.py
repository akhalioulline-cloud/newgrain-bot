"""Flat team wall: one chronological message stream (replaces feed_posts + threaded
feed_comments). Messages can reply-to/quote another message; @flagleaf summons the bot;
photos still auto-get a bot reply. The old feed_* tables are kept (legacy web app) and their
content is migrated into wall_messages so the native wall shows history.

Revision ID: 0041
Revises: 0040
Create Date: 2026-07-05
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0041"
down_revision: Union[str, None] = "0040"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS wall_messages (
            id            BIGSERIAL PRIMARY KEY,
            farm_id       INTEGER NOT NULL,
            author_id     INTEGER REFERENCES users(id),         -- NULL = bot
            is_bot        BOOLEAN NOT NULL DEFAULT false,
            body          TEXT,
            submission_id UUID REFERENCES submissions(id),      -- photo/video message
            field_id      INTEGER REFERENCES fields(id),
            reply_to      BIGINT REFERENCES wall_messages(id),  -- quoted message
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_wall_farm ON wall_messages(farm_id, created_at DESC)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS wall_reactions (
            message_id BIGINT NOT NULL REFERENCES wall_messages(id) ON DELETE CASCADE,
            user_id    INTEGER NOT NULL REFERENCES users(id),
            verdict    TEXT NOT NULL,                           -- 'up' | 'down'
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (message_id, user_id)
        )
        """
    )

    # ── migrate existing feed content into the flat wall (best-effort; keeps history) ──
    op.execute("ALTER TABLE wall_messages ADD COLUMN IF NOT EXISTS _src TEXT")
    # posts → messages
    op.execute(
        """
        INSERT INTO wall_messages (farm_id, author_id, is_bot, body, submission_id, field_id, created_at, _src)
        SELECT farm_id, author_id, false, body, submission_id, field_id, created_at, 'post:'||id
        FROM feed_posts
        WHERE NOT EXISTS (SELECT 1 FROM wall_messages w WHERE w._src = 'post:'||feed_posts.id)
        """
    )
    # comments → messages, replying to their (now migrated) post
    op.execute(
        """
        INSERT INTO wall_messages (farm_id, author_id, is_bot, body, reply_to, created_at, _src)
        SELECT p.farm_id, c.author_id, c.is_bot, c.body,
               (SELECT w.id FROM wall_messages w WHERE w._src = 'post:'||c.post_id),
               c.created_at, 'comment:'||c.id
        FROM feed_comments c JOIN feed_posts p ON p.id = c.post_id
        WHERE NOT EXISTS (SELECT 1 FROM wall_messages w WHERE w._src = 'comment:'||c.id)
        """
    )
    # reactions → wall_reactions (on the migrated post message)
    op.execute(
        """
        INSERT INTO wall_reactions (message_id, user_id, verdict, created_at)
        SELECT (SELECT w.id FROM wall_messages w WHERE w._src = 'post:'||r.post_id), r.user_id, r.verdict, r.created_at
        FROM feed_reactions r
        WHERE EXISTS (SELECT 1 FROM wall_messages w WHERE w._src = 'post:'||r.post_id)
        ON CONFLICT (message_id, user_id) DO NOTHING
        """
    )
    op.execute("ALTER TABLE wall_messages DROP COLUMN IF EXISTS _src")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS wall_reactions")
    op.execute("DROP TABLE IF EXISTS wall_messages")
