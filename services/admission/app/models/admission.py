import uuid
from datetime import UTC, date, datetime

from sqlalchemy import JSON, CheckConstraint, Date, DateTime, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (
        Index("ix_applications_status", "status"),
        Index("ix_applications_submitted_at", "submitted_at"),
        Index("ix_applications_submitted_by", "submitted_by"),
        CheckConstraint(
            "status IN ('SUBMITTED', 'UNDER_REVIEW', 'APPROVED', 'REJECTED', 'ENROLLED')", name="status_valid"
        ),
        CheckConstraint("submitted_by_role IN ('admin', 'parent')", name="submitter_role_valid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    applicant_name: Mapped[str] = mapped_column(String(120))
    date_of_birth: Mapped[date] = mapped_column(Date)
    class_applied: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), default="SUBMITTED")
    review_notes: Mapped[str | None] = mapped_column(Text)
    student_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)  # set on enrollment (owned by Student Service)
    submitted_by_role: Mapped[str] = mapped_column(String(10), default="parent")
    submitted_by: Mapped[str] = mapped_column(String(64))  # user id from the JWT (no FK: Auth owns users)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    parents: Mapped[list["ApplicationParent"]] = relationship(
        back_populates="application", cascade="all, delete-orphan", lazy="selectin"
    )


class ApplicationParent(Base):
    __tablename__ = "application_parents"
    __table_args__ = (Index("ix_application_parents_application_id", "application_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(254))
    phone: Mapped[str] = mapped_column(String(20))
    relationship_type: Mapped[str] = mapped_column("relationship", String(20), default="GUARDIAN")

    application: Mapped[Application] = relationship(back_populates="parents")


class OutboxEvent(Base):
    """Events written in the SAME transaction as the data change, published to SQS afterwards."""

    __tablename__ = "outbox_events"
    __table_args__ = (Index("ix_outbox_unpublished", "published_at", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    event_type: Mapped[str] = mapped_column(String(80))
    payload: Mapped[dict] = mapped_column(JSON().with_variant(JSONB(), "postgresql"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(default=0)
