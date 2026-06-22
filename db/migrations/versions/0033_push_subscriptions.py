"""push_subscriptions — Web Push device subscriptions for the PWA

Each row = one browser/device that opted into notifications, tied to the agronomist's
tg_user_id (same id the web session resolves to). Dead endpoints are pruned on 404/410.

Revision ID: 0033
Revises: 0032
Create Date: 2026-06-22
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0033"
down_revision: Union[str, None] = "0032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS push_subscriptions (
            id         BIGSERIAL PRIMARY KEY,
            tg_user_id BIGINT NOT NULL,
            endpoint   TEXT NOT NULL UNIQUE,
            p256dh     TEXT NOT NULL,
            auth       TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS push_subs_tg ON push_subscriptions (tg_user_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS push_subscriptions")
