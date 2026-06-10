"""add submissions.comment_voice_text_en (English translation of voice notes)

Almas often names the weed/disease in his voice note. The annotator (and a
future non-Russian-speaking freelancer) needs that in English. We store a
Whisper translate-task rendering of the voice alongside the Russian transcript.

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-10
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE submissions ADD COLUMN comment_voice_text_en TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE submissions DROP COLUMN comment_voice_text_en")
