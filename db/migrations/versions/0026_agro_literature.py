"""agro_literature — open-access (CC BY) agronomy literature for RAG citations

Pilot corpus for grounding the chat assistant in real Russian agronomic science
(CyberLeninka, open-access, CC BY — attribution required, which the bot provides by
citing the source). NOT the copyrighted manufacturer atlases. See
docs/knowledge-corpus-strategy.md and LICENSING.md §1(в)/§3.

Revision ID: 0026
Revises: 0025
Create Date: 2026-06-19
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0026"
down_revision: Union[str, None] = "0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS agro_literature (
            id SERIAL PRIMARY KEY,
            source VARCHAR(40) DEFAULT 'cyberleninka',
            journal TEXT,
            title TEXT NOT NULL,
            authors TEXT,
            publisher TEXT,
            year INT,
            url TEXT UNIQUE NOT NULL,
            license TEXT,
            abstract TEXT,
            lang VARCHAR(8),
            ingested_at TIMESTAMP DEFAULT NOW()
        )
        """
    )
    # Russian full-text index over title + abstract for retrieval.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_agrolit_fts ON agro_literature "
        "USING GIN (to_tsvector('russian', coalesce(title,'') || ' ' || coalesce(abstract,'')))"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS agro_literature")
