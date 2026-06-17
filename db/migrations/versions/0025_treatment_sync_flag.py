"""field_treatments.cropwise_synced_at — flag for the bot→CropWise push

The bot logs an operation to field_treatments AND pushes it to CropWise. The two
writes aren't one transaction: if the local insert succeeds but the CropWise push
fails (network/500), the row was silently stranded — no record it never reached
CropWise, no way to find or retry it.

This column records a SUCCESSFUL push (timestamp). A failed push leaves it NULL, so
`db.get_unsynced_bot_treatments()` / the admin `/unsynced` command can surface and
re-push stranded rows. Existing rows are NULL = "sync state unknown"; the recovery
query scopes to source='bot' rows newer than this migration, so the historical
CropWise-imported backlog isn't mistaken for unsynced work.

Revision ID: 0025
Revises: 0024
Create Date: 2026-06-17
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0025"
down_revision: Union[str, None] = "0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE field_treatments ADD COLUMN IF NOT EXISTS cropwise_synced_at TIMESTAMP")


def downgrade() -> None:
    op.execute("ALTER TABLE field_treatments DROP COLUMN IF EXISTS cropwise_synced_at")
