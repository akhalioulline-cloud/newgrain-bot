"""agro_literature.full_text — store the article body (CC BY) for richer grounding

CyberLeninka articles carry the full OCR'd text on the page under CC BY. We keep it
alongside the abstract (retrieval still ranks on title+abstract for now; full_text feeds
deeper answers and future embeddings).

Revision ID: 0027
Revises: 0026
Create Date: 2026-06-19
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0027"
down_revision: Union[str, None] = "0026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE agro_literature ADD COLUMN IF NOT EXISTS full_text TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE agro_literature DROP COLUMN IF EXISTS full_text")
