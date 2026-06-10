"""add submissions.comment_text_en (English translation of typed notes)

Mirrors comment_voice_text_en for voice notes: Almas's typed Russian comments
also get an English translation (YandexGPT, species-grounded) so the annotator
sees them in English.

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-10
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE submissions ADD COLUMN comment_text_en TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE submissions DROP COLUMN comment_text_en")
