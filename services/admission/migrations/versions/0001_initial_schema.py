"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-24 14:13:52.158488
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
        "applications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("applicant_name", sa.String(length=120), nullable=False),
        sa.Column("date_of_birth", sa.Date(), nullable=False),
        sa.Column("class_applied", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("student_id", sa.Uuid(), nullable=True),
        sa.Column("submitted_by_role", sa.String(length=10), nullable=False),
        sa.Column("submitted_by", sa.String(length=64), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('SUBMITTED', 'UNDER_REVIEW', 'APPROVED', 'REJECTED', 'ENROLLED')",
            name=op.f("ck_applications_status_valid"),
        ),
        sa.CheckConstraint(
            "submitted_by_role IN ('admin', 'parent')", name=op.f("ck_applications_submitter_role_valid")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_applications")),
    )
    op.create_index("ix_applications_status", "applications", ["status"], unique=False)
    op.create_index("ix_applications_submitted_at", "applications", ["submitted_at"], unique=False)
    op.create_index("ix_applications_submitted_by", "applications", ["submitted_by"], unique=False)
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
        "application_parents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column("relationship", sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(
            ["application_id"],
            ["applications.id"],
            name=op.f("fk_application_parents_application_id_applications"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_application_parents")),
    )
    op.create_index("ix_application_parents_application_id", "application_parents", ["application_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_application_parents_application_id", table_name="application_parents")
    op.drop_table("application_parents")
    op.drop_index("ix_outbox_unpublished", table_name="outbox_events")
    op.drop_table("outbox_events")
    op.drop_index("ix_applications_submitted_by", table_name="applications")
    op.drop_index("ix_applications_submitted_at", table_name="applications")
    op.drop_index("ix_applications_status", table_name="applications")
    op.drop_table("applications")
