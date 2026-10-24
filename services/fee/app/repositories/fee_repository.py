import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import func, or_, select

from app.models.fee import Fee, FeeStructure
from app.repositories.outbox_repository import OutboxRepository
from app.schemas.fee import FeeStatus


class FeeRepository(OutboxRepository):
    def structure_exists(self, class_id: uuid.UUID, academic_year: str, name: str) -> bool:
        return (
            self.session.scalar(
                select(FeeStructure.id).where(
                    FeeStructure.class_id == class_id,
                    FeeStructure.academic_year == academic_year,
                    FeeStructure.name == name,
                )
            )
            is not None
        )

    def fee_exists(self, student_id: uuid.UUID, structure_id: uuid.UUID) -> bool:
        return (
            self.session.scalar(select(Fee.id).where(Fee.student_id == student_id, Fee.structure_id == structure_id))
            is not None
        )

    def search_fees(
        self,
        *,
        today: date,
        student_ids: list[uuid.UUID] | None,
        status: FeeStatus | None,
        outstanding: bool,
        offset: int,
        limit: int,
    ) -> tuple[list[Fee], int]:
        """`student_ids=None` means no restriction (admin); a list restricts to those students."""
        where: list[Any] = []
        if student_ids is not None:
            where.append(Fee.student_id.in_(student_ids))
        if outstanding:
            where.append(Fee.status != FeeStatus.PAID)
        if status is FeeStatus.OVERDUE:
            where += [Fee.status != FeeStatus.PAID, Fee.due_date < today]
        elif status is FeeStatus.PAID:
            where.append(Fee.status == FeeStatus.PAID)
        elif status:  # PENDING / PARTIAL that are not yet overdue
            where += [Fee.status == status.value, Fee.due_date >= today]
        total = self.session.scalar(select(func.count(Fee.id)).where(*where)) or 0
        rows = self.session.scalars(
            select(Fee).where(*where).order_by(Fee.due_date, Fee.student_name, Fee.id).offset(offset).limit(limit)
        )
        return list(rows), total

    def due_for_reminder(self, *, today: date, remind_before: datetime, limit: int) -> list[Fee]:
        """Unpaid fees past their due date that have contacts and were not reminded recently. Oldest debt first.
        SKIP LOCKED: if two runs ever overlap, each fee still goes to exactly one of them."""
        return list(
            self.session.scalars(
                select(Fee)
                .where(
                    Fee.status != FeeStatus.PAID.value,
                    Fee.due_date < today,
                    Fee.parents.is_not(None),
                    or_(Fee.last_reminded_at.is_(None), Fee.last_reminded_at < remind_before),
                )
                .order_by(Fee.due_date, Fee.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )

    def lock_fee(self, fee_id: uuid.UUID) -> Fee | None:
        """Row lock: a second payment for the same fee waits here until the first commits.

        `populate_existing` is essential. The fee was already loaded earlier in this request; without it
        the ORM would hand back that old object with its OLD amount_paid, and we would add to a stale
        number (a lost update) even though we hold the lock."""
        return self.session.scalar(
            select(Fee).where(Fee.id == fee_id).with_for_update().execution_options(populate_existing=True)
        )
