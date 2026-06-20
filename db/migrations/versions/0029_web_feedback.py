"""web_feedback — thumbs up/down on web AI answers (ai.flagleaf.ru)

Lightweight learning signal: which answers landed and which didn't, so the grounding/prompts
can be improved. Not analytics/gamification (spec §3.3) — it's answer-quality feedback.

Revision ID: 0029
Revises: 0028
Create Date: 2026-06-20
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0029"
down_revision: Union[str, None] = "0028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS web_feedback (
            id         BIGSERIAL PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            vote       TEXT NOT NULL,          -- 'up' | 'down'
            crop       TEXT,
            question   TEXT,
            answer     TEXT,
            ip         TEXT
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS web_feedback")
