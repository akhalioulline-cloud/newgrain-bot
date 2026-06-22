"""users.email — login codes can be delivered by email (noreply@flagleaf.ru)

Lets agronomists log in to ai.flagleaf.ru/app without Telegram/VPN: they enter their
email, we mail the same 6-digit code the bot's /weblogin issues. Stored lowercased;
unique so one email maps to exactly one user.

Revision ID: 0032
Revises: 0031
Create Date: 2026-06-22
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0032"
down_revision: Union[str, None] = "0031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS email TEXT")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS users_email_uniq "
        "ON users (lower(email)) WHERE email IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS users_email_uniq")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS email")
