"""product_prices — per-product unit price for ruble-denominated savings

Lets the field-plan generator turn the CropWise spray baseline (product + dose + area)
into an actual ₽ figure. Price is per base unit (л or кг); dose is parsed and matched to it.
Populated by admins via /setprice (the founder supplies real prices — we never invent them).

Revision ID: 0034
Revises: 0033
Create Date: 2026-06-23
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0034"
down_revision: Union[str, None] = "0033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS product_prices (
            product_name TEXT PRIMARY KEY,
            price        NUMERIC(12,2) NOT NULL,
            unit         TEXT NOT NULL,           -- 'л' or 'кг'
            note         TEXT,
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS product_prices")
