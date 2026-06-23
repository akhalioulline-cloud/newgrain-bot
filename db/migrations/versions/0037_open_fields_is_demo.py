"""Open all fields to the pilot; keep the original 12 as 'demonstration' fields

Pilot v2 expansion: agronomists report whatever field they're on (no wasted travel), so
is_pilot opens to every real field. The original 12 pilot fields become the 'demonstration'
set (is_demo) — the ones we want regular, repeated scouting on for the savings proof, and
that the app's motivation panel nudges them back to.

Revision ID: 0037
Revises: 0036
Create Date: 2026-06-23
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0037"
down_revision: Union[str, None] = "0036"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE fields ADD COLUMN IF NOT EXISTS is_demo BOOLEAN NOT NULL DEFAULT false")
    # the current 12 pilots become the demonstration fields…
    op.execute("UPDATE fields SET is_demo = true WHERE is_pilot = true")
    # …and every real field (single farm) opens for selection.
    op.execute("UPDATE fields SET is_pilot = true WHERE farm_id = 1")


def downgrade() -> None:
    # restore: only the demonstration fields stay flagged as pilot
    op.execute("UPDATE fields SET is_pilot = is_demo WHERE farm_id = 1")
    op.execute("ALTER TABLE fields DROP COLUMN IF EXISTS is_demo")
