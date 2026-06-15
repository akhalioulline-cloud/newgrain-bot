"""add farms.region — the data-residency hook for a future dual-market launch

A farm's region records WHERE its data must live (RU personal data stays on
Russian infra under 152-ФЗ; a future non-RU channel keeps its customers' data
abroad). Nothing reads it yet — it's a cheap forward hook so the eventual
region-aware routing has a column to key on, and so today's single farm is
explicitly tagged 'RU' rather than implicitly assumed.

See docs/continuity-and-portability.md for the dual-market / relocation model.

Revision ID: 0021
Revises: 0020
Create Date: 2026-06-15
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE farms ADD COLUMN IF NOT EXISTS region TEXT NOT NULL DEFAULT 'RU'")


def downgrade() -> None:
    op.execute("ALTER TABLE farms DROP COLUMN IF EXISTS region")
