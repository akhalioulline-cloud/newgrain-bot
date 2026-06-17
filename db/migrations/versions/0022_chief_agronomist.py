"""chief_agronomist role: promote Almas (the CA / reviewer)

A new role above 'agronomist'. Junior agronomists' submissions are forwarded to a
chief_agronomist for per-attribute confirmation before they reach the labeling
pipeline (handlers + states). The CA's own workflow is unchanged (posts directly).
Almas Kasumov (tg_user_id 1895200085) is the CA; everyone else keeps their role.

Revision ID: 0022
Revises: 0021
Create Date: 2026-06-17
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE users SET role = 'chief_agronomist' WHERE tg_user_id = 1895200085")


def downgrade() -> None:
    op.execute("UPDATE users SET role = 'agronomist' WHERE tg_user_id = 1895200085")
