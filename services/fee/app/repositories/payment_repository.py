import uuid
from typing import Any

from sqlalchemy import func, select

from app.models.fee import Payment
from app.repositories.outbox_repository import OutboxRepository


class PaymentRepository(OutboxRepository):
    def by_idempotency_key(self, key: str) -> Payment | None:
        return self.session.scalar(select(Payment).where(Payment.idempotency_key == key))

    def search(
        self,
        *,
        student_ids: list[uuid.UUID] | None,
        fee_id: uuid.UUID | None,
        status: str | None,
        offset: int,
        limit: int,
    ) -> tuple[list[Payment], int]:
        where: list[Any] = []
        if student_ids is not None:
            where.append(Payment.student_id.in_(student_ids))
        if fee_id:
            where.append(Payment.fee_id == fee_id)
        if status:
            where.append(Payment.status == status)
        total = self.session.scalar(select(func.count(Payment.id)).where(*where)) or 0
        rows = self.session.scalars(
            select(Payment).where(*where).order_by(Payment.created_at.desc(), Payment.id).offset(offset).limit(limit)
        )
        return list(rows), total
