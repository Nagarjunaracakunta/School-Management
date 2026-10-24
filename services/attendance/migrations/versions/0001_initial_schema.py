"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-24 14:13:53.249268
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
        "attendance",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("subject_type", sa.String(length=7), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("subject_name", sa.String(length=120), nullable=False),
        sa.Column("class_name", sa.String(length=50), nullable=True),
        sa.Column("section_name", sa.String(length=20), nullable=True),
        sa.Column("attendance_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=7), nullable=False),
        sa.Column("marked_by", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('PRESENT', 'ABSENT', 'LATE')", name=op.f("ck_attendance_status_valid")),
        sa.CheckConstraint("subject_type IN ('student', 'teacher')", name=op.f("ck_attendance_subject_type_valid")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_attendance")),
        sa.UniqueConstraint(
            "subject_type",
            "subject_id",
            "attendance_date",
            name=op.f("uq_attendance_subject_type_subject_id_attendance_date"),
        ),
    )
    op.create_index(
        "ix_attendance_class_section_date",
        "attendance",
        ["class_name", "section_name", "attendance_date"],
        unique=False,
    )
    op.create_index("ix_attendance_date", "attendance", ["attendance_date"], unique=False)
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


def downgrade() -> None:
    op.drop_index("ix_outbox_unpublished", table_name="outbox_events")
    op.drop_table("outbox_events")
    op.drop_index("ix_attendance_date", table_name="attendance")
    op.drop_index("ix_attendance_class_section_date", table_name="attendance")
    op.drop_table("attendance")
