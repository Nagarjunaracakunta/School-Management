"""remember parent contacts and the last reminder on each fee

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-24

Backward compatible ("expand" step, ADR 0002): both columns are nullable, so the previous version of the service keeps
working while this one rolls out. Fees created before this migration have no contacts and are simply never reminded.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "fees",
        sa.Column(
            "parents",
            sa.JSON(none_as_null=True).with_variant(
                postgresql.JSONB(astext_type=sa.Text(), none_as_null=True), "postgresql"
            ),
            nullable=True,
        ),
    )
    op.add_column("fees", sa.Column("last_reminded_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("fees", "last_reminded_at")
    op.drop_column("fees", "parents")
