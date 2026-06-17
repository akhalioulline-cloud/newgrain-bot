"""annotator role: Евгения Снеговская (annotates in CVAT)

Annotation happens in CVAT, not the bot — so within the bot this role's only
behaviour is to RECEIVE the labeling reference sheet + batch-ready notification
(labeling/reference.py --deliver → alert.send(annotators=True)), which otherwise
go to admins only. Not a data collector, so the agronomist→CA review gate doesn't
apply. Евгения (tg_user_id 5872820319) was an agronomist; reclassify her.

Revision ID: 0023
Revises: 0022
Create Date: 2026-06-17
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0023"
down_revision: Union[str, None] = "0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE users SET role = 'annotator' WHERE tg_user_id = 5872820319")


def downgrade() -> None:
    op.execute("UPDATE users SET role = 'agronomist' WHERE tg_user_id = 5872820319")
