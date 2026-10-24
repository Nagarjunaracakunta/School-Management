"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-24 14:13:53.595369
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("channel", sa.String(length=5), nullable=False),
        sa.Column("recipient", sa.String(length=254), nullable=False),
        sa.Column("recipient_name", sa.String(length=120), nullable=True),
        sa.Column("recipient_email", sa.String(length=254), nullable=True),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=7), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("provider_message_id", sa.String(length=100), nullable=True),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("channel IN ('EMAIL', 'SMS')", name=op.f("ck_notifications_channel_valid")),
        sa.CheckConstraint("status IN ('PENDING', 'SENT', 'FAILED')", name=op.f("ck_notifications_status_valid")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
        sa.UniqueConstraint(
            "event_id", "recipient", "channel", name=op.f("uq_notifications_event_id_recipient_channel")
        ),
    )
    op.create_index("ix_notifications_event_id", "notifications", ["event_id"], unique=False)
    op.create_index("ix_notifications_recipient_email", "notifications", ["recipient_email"], unique=False)
    op.create_index("ix_notifications_status_created", "notifications", ["status", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_notifications_status_created", table_name="notifications")
    op.drop_index("ix_notifications_recipient_email", table_name="notifications")
    op.drop_index("ix_notifications_event_id", table_name="notifications")
    op.drop_table("notifications")
