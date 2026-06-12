"""link a photo to a recent field treatment (photo ↔ spray context)

Adds an optional treatment context to a submission: the agronomist, after a
photo of a real field, can tap which recent operation it relates to. Captures
the photo↔treatment↔days-elapsed link that CropWise doesn't have — the agent
later reasons "lesion 6 days after a triazole", "chlorosis 3 days post-spray".

- treatment_id   → the picked field_treatments row (ON DELETE SET NULL so a
                   treatment reload can't break the submission).
- treatment_note → free-text / voice transcript for the "Другое" case (a spray
                   too recent to be in the exported history yet).

Revision ID: 0019
Revises: 0018
Create Date: 2026-06-12
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE submissions "
        "ADD COLUMN treatment_id INTEGER REFERENCES field_treatments(id) "
        "ON DELETE SET NULL, "
        "ADD COLUMN treatment_note TEXT"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE submissions "
        "DROP COLUMN IF EXISTS treatment_id, "
        "DROP COLUMN IF EXISTS treatment_note"
    )
