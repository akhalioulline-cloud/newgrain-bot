"""dedup field_treatments + unique natural-key index (idempotent ingest)

Makes treatment ingest re-runnable and safe for a future CropWise-API sync.
Identical operations — same field / date / operation / product / dose / area —
collapse to a single row regardless of `source`, so a manual multiprotocol load
now and an API sync later can NEVER double-count the same spray. `source` is kept
on the row for provenance but is deliberately NOT part of the key, so the
guarantee holds across sources without anyone having to delete-by-source first.

NULLS NOT DISTINCT (Postgres 15+) is required so rows with no product — tillage,
sowing — still dedup on field/date/operation/area instead of every NULL counting
as unique.

Revision ID: 0018
Revises: 0017
Create Date: 2026-06-12
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NATKEY = "field_name, treatment_date, operation, product, dose, area_ha"


def upgrade() -> None:
    # Collapse any pre-existing duplicates first (keep the earliest row by id),
    # NULL-safe, so the unique index can be created cleanly whatever is in the
    # table today.
    op.execute(
        """
        DELETE FROM field_treatments a USING field_treatments b
        WHERE a.id > b.id
          AND a.field_name     IS NOT DISTINCT FROM b.field_name
          AND a.treatment_date IS NOT DISTINCT FROM b.treatment_date
          AND a.operation      IS NOT DISTINCT FROM b.operation
          AND a.product        IS NOT DISTINCT FROM b.product
          AND a.dose           IS NOT DISTINCT FROM b.dose
          AND a.area_ha        IS NOT DISTINCT FROM b.area_ha
        """
    )
    op.execute(
        f"CREATE UNIQUE INDEX uq_treat_natkey ON field_treatments "
        f"({_NATKEY}) NULLS NOT DISTINCT"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_treat_natkey")
