import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import JSON, CheckConstraint, Date, DateTime, ForeignKey, Index, Numeric, String, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


Money = Numeric(10, 2)  # exact decimal: never use floats for money


class FeeStructure(Base):
    """A price list entry: 'Tuition Term 1 for Grade 3 in 2026-27 costs 15000, due 2026-07-10'."""

    __tablename__ = "fee_structures"
    __table_args__ = (
        UniqueConstraint("class_id", "academic_year", "name"),
        CheckConstraint("amount > 0", name="amount_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(80))
    class_id: Mapped[uuid.UUID] = mapped_column(Uuid)  # owned by Student Service, so no FK
    class_name: Mapped[str] = mapped_column(String(50))
    academic_year: Mapped[str] = mapped_column(String(7))
    amount: Mapped[Decimal] = mapped_column(Money)
    due_date: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Fee(Base):
    """What one student owes for one structure entry."""

    __tablename__ = "fees"
    __table_args__ = (
        UniqueConstraint("student_id", "structure_id"),  # cannot be assigned twice
        Index("ix_fees_student_id", "student_id"),
        Index("ix_fees_status_due", "status", "due_date"),
        CheckConstraint("amount_due > 0", name="amount_due_positive"),
        # The last line of defence against overpayment, whatever the application code does
        CheckConstraint("amount_paid >= 0 AND amount_paid <= amount_due", name="paid_within_due"),
        CheckConstraint("status IN ('PENDING', 'PARTIAL', 'PAID')", name="status_valid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    student_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    student_name: Mapped[str] = mapped_column(String(120))  # copied so lists need no cross-service call
    structure_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fee_structures.id"))
    name: Mapped[str] = mapped_column(String(80))
    amount_due: Mapped[Decimal] = mapped_column(Money)
    amount_paid: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    due_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(10), default="PENDING")  # PENDING | PARTIAL | PAID
    # Contact details of the parents, copied from the Student service when the fee is assigned, so the nightly reminder
    # job needs no cross-service call and no login token. Personal data: it lives only as long as the fee does.
    parents: Mapped[list | None] = mapped_column(
        JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql")
    )
    last_reminded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    @property
    def outstanding(self) -> Decimal:
        return self.amount_due - self.amount_paid


class Payment(Base):
    """Append-only record of money received. Never updated or deleted after creation."""

    __tablename__ = "payments"
    __table_args__ = (
        Index("ix_payments_fee_id", "fee_id"),
        Index("ix_payments_student_id", "student_id"),
        Index("ix_payments_created_at", "created_at"),
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("balance_after >= 0", name="balance_non_negative"),
        CheckConstraint("method IN ('CARD', 'UPI', 'CASH')", name="method_valid"),
        CheckConstraint("status IN ('COMPLETED', 'FAILED', 'PENDING')", name="status_valid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    fee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fees.id"))
    # Snapshot of facts at payment time, so a receipt never changes later
    student_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    student_name: Mapped[str] = mapped_column(String(120))
    fee_name: Mapped[str] = mapped_column(String(80))
    amount: Mapped[Decimal] = mapped_column(Money)
    balance_after: Mapped[Decimal] = mapped_column(Money)
    method: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(10), default="COMPLETED")
    receipt_no: Mapped[str] = mapped_column(String(30), unique=True)
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True)
    paid_by: Mapped[str] = mapped_column(String(64))  # user id from the JWT
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


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
