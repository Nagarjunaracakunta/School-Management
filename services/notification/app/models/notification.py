import datetime as dt
import uuid

from sqlalchemy import CheckConstraint, DateTime, Index, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class Notification(Base):
    """One message to one person on one channel.

    The UNIQUE(event_id, recipient, channel) key makes event processing idempotent: SQS may deliver the
    same event twice, but the second pass finds these rows already there and creates nothing.
    """

    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("event_id", "recipient", "channel"),
        Index("ix_notifications_status_created", "status", "created_at"),
        Index("ix_notifications_recipient_email", "recipient_email"),
        Index("ix_notifications_event_id", "event_id"),
        CheckConstraint("channel IN ('EMAIL', 'SMS')", name="channel_valid"),
        CheckConstraint("status IN ('PENDING', 'SENT', 'FAILED')", name="status_valid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)  # NULL for manually created messages
    event_type: Mapped[str] = mapped_column(String(80))
    channel: Mapped[str] = mapped_column(String(5))  # EMAIL | SMS
    recipient: Mapped[str] = mapped_column(String(254))  # the address used: an email or a phone number
    recipient_name: Mapped[str | None] = mapped_column(String(120))
    # The person's email even on SMS rows, so a parent can be shown "all messages sent to me"
    recipient_email: Mapped[str | None] = mapped_column(String(254))
    subject: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(7), default="PENDING")  # PENDING | SENT | FAILED
    attempts: Mapped[int] = mapped_column(default=0)
    last_error: Mapped[str | None] = mapped_column(String(500))
    provider_message_id: Mapped[str | None] = mapped_column(String(100))  # SNS MessageId, for tracing
    created_by: Mapped[str | None] = mapped_column(String(64))  # user id, for manual messages
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
