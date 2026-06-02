"""surface apera + lamium as inline-keyboard species (regional-top)

Almas reported Метлица обыкновенная (Apera spica-venti) and Яснотка
стеблеобъемлющая (Lamium amplexicaule) on winter wheat via the /Другой
free-text path; both are now CVAT training classes (apera, lamium). Make them
tappable species buttons so they're captured consistently going forward.

- Apera spica-venti: already in the table (migration 0005, non-top) → flip to
  regional-top.
- Lamium amplexicaule: new row, regional-top.

This is a deliberate (CAO-driven) promotion, not the frequency-based default in
labeling/schema_promotion_policy.md — these two are seasonally active now.

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-02
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE weed_species SET is_regional_top = true "
        "WHERE latin_name = 'Apera spica-venti'"
    )
    op.execute(
        """
        INSERT INTO weed_species (latin_name, russian_name, is_regional_top)
        VALUES ('Lamium amplexicaule', 'Яснотка стеблеобъемлющая', true)
        """
    )


def downgrade() -> None:
    op.execute(
        "UPDATE weed_species SET is_regional_top = false "
        "WHERE latin_name = 'Apera spica-venti'"
    )
    op.execute(
        "DELETE FROM weed_species WHERE latin_name = 'Lamium amplexicaule'"
    )
