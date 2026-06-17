"""admin: promote Алексей Дурнев

Full admin = DB role 'admin' (role-based checks incl. the CA review gate) +
tg id in ADMIN_TG_IDS (command menu, /problem recipients, bootstrap) — the latter
is set in the server .env. This migration handles the DB role.
Алексей Дурнев (tg_user_id 5425284392) was an agronomist.

Revision ID: 0024
Revises: 0023
Create Date: 2026-06-17
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0024"
down_revision: Union[str, None] = "0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE users SET role = 'admin' WHERE tg_user_id = 5425284392")


def downgrade() -> None:
    op.execute("UPDATE users SET role = 'agronomist' WHERE tg_user_id = 5425284392")
