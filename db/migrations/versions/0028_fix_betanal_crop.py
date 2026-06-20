"""Fix Госкаталог data error: Бетанал 22 wrongly listed for soy/sunflower/rapeseed

Бетанал 22 (десмедифам + фенмедифам) is a BEET-ONLY herbicide, but its crop field in the
ingested registry wrongly read «Свекла…, подсолнечник, соя, рапс». So the assistant
recommended it for soy (Almas's report — десмедифам/фенмедифам would kill the soy). Isolated
data error (the only beet-specific active that listed soy); correct it to beet-only.

Revision ID: 0028
Revises: 0027
Create Date: 2026-06-20
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0028"
down_revision: Union[str, None] = "0027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE pesticide_applications "
        "SET crop = 'Свекла сахарная, столовая (кроме пучкового товара)' "
        "WHERE product_name = 'Бетанал 22' AND crop ILIKE '%соя%'"
    )


def downgrade() -> None:
    pass  # the prior value was erroneous — nothing worth restoring
