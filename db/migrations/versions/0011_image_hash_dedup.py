"""add submissions.image_hash for upload deduplication

Stores the sha256 of each photo's bytes so a byte-identical re-upload by the
same agronomist is caught at upload time and skipped (the June-2026 incident:
during the Telegram-relay outage Almas re-sent photos that had appeared to
fail, creating duplicates). Indexed by (user_id, image_hash) for the lookup.

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-10
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE submissions ADD COLUMN image_hash VARCHAR(64)")
    op.execute("CREATE INDEX idx_subm_user_hash ON submissions (user_id, image_hash)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_subm_user_hash")
    op.execute("ALTER TABLE submissions DROP COLUMN image_hash")
