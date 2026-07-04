"""Group feed: shared team posts, discussion threads, chief reactions

Turns the private assistant into a shared team feed. Every media upload or text observation
by an agronomist becomes a post the whole farm sees, with the bot's reply attached. Members
comment (a discussion thread the bot learns from); the chief agronomist reacts 👍/👎 (his
verdict is the ground-truth training signal). The private you↔bot DM stays client-side.

Revision ID: 0038
Revises: 0037
Create Date: 2026-07-04
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0038"
down_revision: Union[str, None] = "0037"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS feed_posts (
            id           BIGSERIAL PRIMARY KEY,
            farm_id      INTEGER NOT NULL,
            author_id    INTEGER NOT NULL REFERENCES users(id),
            submission_id UUID REFERENCES submissions(id),   -- media post; NULL = text-only
            field_id     INTEGER REFERENCES fields(id),
            body         TEXT,                                -- author's caption / text
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_feed_posts_farm ON feed_posts(farm_id, created_at DESC)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS feed_comments (
            id         BIGSERIAL PRIMARY KEY,
            post_id    BIGINT NOT NULL REFERENCES feed_posts(id) ON DELETE CASCADE,
            author_id  INTEGER REFERENCES users(id),          -- NULL = bot
            is_bot     BOOLEAN NOT NULL DEFAULT false,
            body       TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_feed_comments_post ON feed_comments(post_id, created_at)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS feed_reactions (
            post_id    BIGINT NOT NULL REFERENCES feed_posts(id) ON DELETE CASCADE,
            user_id    INTEGER NOT NULL REFERENCES users(id),
            verdict    TEXT NOT NULL,                          -- 'up' | 'down'
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (post_id, user_id)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS feed_reactions")
    op.execute("DROP TABLE IF EXISTS feed_comments")
    op.execute("DROP TABLE IF EXISTS feed_posts")
