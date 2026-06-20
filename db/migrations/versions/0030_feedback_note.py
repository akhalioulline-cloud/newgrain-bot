"""web_feedback.note — optional free-text on a 👎 ("что не так?")

Turns a thumbs-down into an actionable correction for the grounding/prompts.

Revision ID: 0030
Revises: 0029
Create Date: 2026-06-20
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0030"
down_revision: Union[str, None] = "0029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE web_feedback ADD COLUMN IF NOT EXISTS note TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE web_feedback DROP COLUMN IF EXISTS note")
