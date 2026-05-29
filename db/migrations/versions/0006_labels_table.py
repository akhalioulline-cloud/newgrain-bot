"""labels table for CVAT-annotated bboxes (Stage 2 MVP)

Adds the labels table referenced by spec §1.5 status flow:
    draft → awaiting_metadata → ready_for_labeling
         → in_labeling → labeled → in_dataset

Bboxes stored as YOLO-normalized coordinates (cx, cy, w, h ∈ [0, 1]) so all
downstream training reads one canonical representation. The CVAT XML coords
(pixel xtl/ytl/xbr/ybr) are converted on import.

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-29
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE labels (
            id SERIAL PRIMARY KEY,
            submission_id UUID NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
            class_label VARCHAR(50) NOT NULL,
            bbox_x NUMERIC(8,7) NOT NULL,   -- center x, normalized
            bbox_y NUMERIC(8,7) NOT NULL,   -- center y, normalized
            bbox_w NUMERIC(8,7) NOT NULL,   -- width, normalized
            bbox_h NUMERIC(8,7) NOT NULL,   -- height, normalized
            confidence NUMERIC(4,3),         -- NULL for human, 0–1 for model
            annotator VARCHAR(50) DEFAULT 'human',
            source VARCHAR(20) DEFAULT 'cvat',
            note TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX idx_labels_subm ON labels(submission_id)")
    op.execute("CREATE INDEX idx_labels_class ON labels(class_label)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS labels")
