import datetime as dt
import uuid

from sqlalchemy import JSON, CheckConstraint, Date, DateTime, Index, String, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class Attendance(Base):
    """One person, one day, one status. Re-marking the same day updates this row (a correction)."""

    __tablename__ = "attendance"
    __table_args__ = (
        UniqueConstraint("subject_type", "subject_id", "attendance_date"),
        Index("ix_attendance_date", "attendance_date"),
        Index("ix_attendance_class_section_date", "class_name", "section_name", "attendance_date"),
        CheckConstraint("subject_type IN ('student', 'teacher')", name="subject_type_valid"),
        CheckConstraint("status IN ('PRESENT', 'ABSENT', 'LATE')", name="status_valid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    subject_type: Mapped[str] = mapped_column(String(7))  # student | teacher
    subject_id: Mapped[uuid.UUID] = mapped_column(Uuid)  # owned by Student Service, so no FK
    # Snapshots, so lists and reports need no cross-service call and history survives later changes
    subject_name: Mapped[str] = mapped_column(String(120))
    class_name: Mapped[str | None] = mapped_column(String(50))
    section_name: Mapped[str | None] = mapped_column(String(20))
    attendance_date: Mapped[dt.date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(7))  # PRESENT | ABSENT | LATE
    marked_by: Mapped[str] = mapped_column(String(64))  # user id from the JWT
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class OutboxEvent(Base):
    """Events written in the SAME transaction as the data change, published to SQS afterwards."""

    __tablename__ = "outbox_events"
    __table_args__ = (Index("ix_outbox_unpublished", "published_at", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    event_type: Mapped[str] = mapped_column(String(80))
    payload: Mapped[dict] = mapped_column(JSON().with_variant(JSONB(), "postgresql"))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    published_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(default=0)
