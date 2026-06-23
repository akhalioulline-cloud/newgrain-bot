"""video_jobs — background transcription queue for scouting videos

Each uploaded scouting video creates a pending job. The collector
(labeling/video_collect.py, cron) transcribes the narration in the background and
writes it into the submission's observation, then marks the job done.

Revision ID: 0036
Revises: 0035
Create Date: 2026-06-23
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0036"
down_revision: Union[str, None] = "0035"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS video_jobs (
            id            BIGSERIAL PRIMARY KEY,
            submission_id UUID NOT NULL,
            video_key     TEXT NOT NULL,
            status        TEXT NOT NULL DEFAULT 'pending',   -- pending | done | failed
            attempts      INTEGER NOT NULL DEFAULT 0,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS video_jobs_pending ON video_jobs (status, created_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS video_jobs")
