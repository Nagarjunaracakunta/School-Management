"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-24 14:13:52.881201
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "fee_structures",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("class_id", sa.Uuid(), nullable=False),
        sa.Column("class_name", sa.String(length=50), nullable=False),
        sa.Column("academic_year", sa.String(length=7), nullable=False),
        sa.Column("amount", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount > 0", name=op.f("ck_fee_structures_amount_positive")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fee_structures")),
        sa.UniqueConstraint(
            "class_id", "academic_year", "name", name=op.f("uq_fee_structures_class_id_academic_year_name")
        ),
    )
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column(
            "payload", sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_outbox_events")),
    )
    op.create_index("ix_outbox_unpublished", "outbox_events", ["published_at", "created_at"], unique=False)
    op.create_table(
        "fees",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("student_name", sa.String(length=120), nullable=False),
        sa.Column("structure_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("amount_due", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("amount_paid", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('PENDING', 'PARTIAL', 'PAID')", name=op.f("ck_fees_status_valid")),
        sa.CheckConstraint("amount_due > 0", name=op.f("ck_fees_amount_due_positive")),
        sa.CheckConstraint("amount_paid >= 0 AND amount_paid <= amount_due", name=op.f("ck_fees_paid_within_due")),
        sa.ForeignKeyConstraint(
            ["structure_id"], ["fee_structures.id"], name=op.f("fk_fees_structure_id_fee_structures")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fees")),
        sa.UniqueConstraint("student_id", "structure_id", name=op.f("uq_fees_student_id_structure_id")),
    )
    op.create_index("ix_fees_status_due", "fees", ["status", "due_date"], unique=False)
    op.create_index("ix_fees_student_id", "fees", ["student_id"], unique=False)
    op.create_table(
        "payments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("fee_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("student_name", sa.String(length=120), nullable=False),
        sa.Column("fee_name", sa.String(length=80), nullable=False),
        sa.Column("amount", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("balance_after", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("method", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("receipt_no", sa.String(length=30), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("paid_by", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("method IN ('CARD', 'UPI', 'CASH')", name=op.f("ck_payments_method_valid")),
        sa.CheckConstraint("status IN ('COMPLETED', 'FAILED', 'PENDING')", name=op.f("ck_payments_status_valid")),
        sa.CheckConstraint("amount > 0", name=op.f("ck_payments_amount_positive")),
        sa.CheckConstraint("balance_after >= 0", name=op.f("ck_payments_balance_non_negative")),
        sa.ForeignKeyConstraint(["fee_id"], ["fees.id"], name=op.f("fk_payments_fee_id_fees")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payments")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_payments_idempotency_key")),
        sa.UniqueConstraint("receipt_no", name=op.f("uq_payments_receipt_no")),
    )
    op.create_index("ix_payments_created_at", "payments", ["created_at"], unique=False)
    op.create_index("ix_payments_fee_id", "payments", ["fee_id"], unique=False)
    op.create_index("ix_payments_student_id", "payments", ["student_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_payments_student_id", table_name="payments")
    op.drop_index("ix_payments_fee_id", table_name="payments")
    op.drop_index("ix_payments_created_at", table_name="payments")
    op.drop_table("payments")
    op.drop_index("ix_fees_student_id", table_name="fees")
    op.drop_index("ix_fees_status_due", table_name="fees")
    op.drop_table("fees")
    op.drop_index("ix_outbox_unpublished", table_name="outbox_events")
    op.drop_table("outbox_events")
    op.drop_table("fee_structures")
