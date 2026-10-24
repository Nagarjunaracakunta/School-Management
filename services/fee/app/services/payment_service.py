import logging
import secrets
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from app.clients.student_client import StudentClient
from app.models.fee import Fee, Payment
from app.repositories.fee_repository import FeeRepository
from app.repositories.payment_repository import PaymentRepository
from app.schemas.fee import FeeStatus, PaymentCreate, PaymentMethod, PaymentOut, ReceiptOut, money_str
from app.services.access import visible_student_ids
from app.utils.errors import ConflictError, NotFoundError
from app.utils.security import CurrentUser, Role

logger = logging.getLogger(__name__)


def payment_out(p: Payment) -> PaymentOut:
    return PaymentOut(
        id=p.id,
        receipt_no=p.receipt_no,
        fee_id=p.fee_id,
        student_id=p.student_id,
        amount=p.amount,
        method=PaymentMethod(p.method),
        status=p.status,
        balance_after=p.balance_after,
        created_at=p.created_at,
    )


def new_receipt_no() -> str:
    # Real accounting systems use a gap-free database sequence (auditors ask about missing numbers).
    # A random suffix is enough for learning; the UNIQUE constraint still guards against a clash.
    return f"RCT-{datetime.now(UTC):%Y%m%d}-{secrets.token_hex(4).upper()}"


class PaymentService:
    def __init__(self, payments: PaymentRepository, fees: FeeRepository, students: StudentClient) -> None:
        self.payments = payments
        self.fees = fees
        self.students = students

    def pay(self, data: PaymentCreate, idempotency_key: str, user: CurrentUser) -> tuple[Payment, bool]:
        """Returns (payment, created). A repeat of the same request returns the original payment."""
        replay = self._replay(data, idempotency_key, user)
        if replay:
            return replay, False

        fee = self.fees.get(Fee, data.fee_id)
        if fee is None:
            raise NotFoundError("Fee not found")
        # Access check + contact details, done BEFORE taking the row lock (never hold a DB lock across a
        # network call). A parent paying someone else's fee gets the same 404 as a missing fee.
        try:
            student = self.students.get_student(str(fee.student_id), user.token)
        except NotFoundError as exc:
            raise NotFoundError("Fee not found") from exc

        # Lock the fee row: two simultaneous payments are processed one after the other,
        # so together they can never pay more than is owed.
        fee = self.fees.lock_fee(data.fee_id)
        # Check for a replay AGAIN, now that we hold the lock: an identical request may have finished
        # while we waited for it. Without this, a retry racing the payment that cleared the fee would be
        # told "already fully paid" instead of getting its own original payment back.
        replay = self._replay(data, idempotency_key, user)
        if replay:
            return replay, False
        if fee.status == FeeStatus.PAID:
            raise ConflictError("This fee is already fully paid")
        if data.amount > fee.outstanding:
            raise ConflictError(f"Amount exceeds the outstanding balance of {fee.outstanding}")

        fee.amount_paid += data.amount
        fee.status = FeeStatus.PAID.value if fee.outstanding == 0 else FeeStatus.PARTIAL.value
        payment = Payment(
            fee_id=fee.id,
            student_id=fee.student_id,
            student_name=fee.student_name,
            fee_name=fee.name,
            amount=data.amount,
            balance_after=fee.outstanding,
            method=data.method.value,
            receipt_no=new_receipt_no(),
            idempotency_key=idempotency_key,
            paid_by=user.id,
        )
        try:
            self.payments.add(payment)
        except ConflictError:
            # Lost a race with the same key arriving twice at once: return the winner.
            replay = self._replay(data, idempotency_key, user)
            if replay:
                return replay, False
            raise
        self.payments.add_event(
            "payment.completed",
            {
                "payment_id": str(payment.id),
                "receipt_no": payment.receipt_no,
                "fee_id": str(fee.id),
                "fee_name": fee.name,
                "student_id": str(fee.student_id),
                "student_name": fee.student_name,
                "amount": money_str(payment.amount),
                "balance_after": money_str(payment.balance_after),
                "method": payment.method,
                "parents": [{"name": p["name"], "email": p["email"], "phone": p["phone"]} for p in student["parents"]],
            },
        )
        self.payments.commit()  # payment + fee balance + event: all or nothing
        logger.info(
            "payment completed",
            extra={"payment_id": str(payment.id), "receipt_no": payment.receipt_no, "amount": str(payment.amount)},
        )
        return payment, True

    def _replay(self, data: PaymentCreate, key: str, user: CurrentUser) -> Payment | None:
        existing = self.payments.by_idempotency_key(key)
        if existing is None:
            return None
        same = (
            existing.paid_by == user.id
            and existing.fee_id == data.fee_id
            and existing.amount == Decimal(data.amount)
            and existing.method == data.method.value
        )
        if not same:
            # Reusing a key for a different request is a client bug; never return someone else's payment.
            raise ConflictError("Idempotency-Key was already used for a different request")
        return existing

    def get(self, payment_id: uuid.UUID, user: CurrentUser) -> Payment:
        payment = self.payments.get(Payment, payment_id)
        if payment is None:
            raise NotFoundError("Payment not found")
        if user.role is not Role.ADMIN:
            try:
                self.students.get_student(str(payment.student_id), user.token)
            except NotFoundError as exc:
                raise NotFoundError("Payment not found") from exc
        return payment

    def receipt(self, payment_id: uuid.UUID, user: CurrentUser) -> ReceiptOut:
        p = self.get(payment_id, user)
        return ReceiptOut(
            receipt_no=p.receipt_no,
            issued_at=p.created_at,
            student_name=p.student_name,
            fee_name=p.fee_name,
            amount_paid=p.amount,
            payment_method=PaymentMethod(p.method),
            balance_after=p.balance_after,
        )

    def list(
        self, user: CurrentUser, *, fee_id: uuid.UUID | None, status: str | None, offset: int, limit: int
    ) -> tuple[list[Payment], int]:
        allowed = visible_student_ids(self.students, user)
        if allowed == []:
            return [], 0
        return self.payments.search(student_ids=allowed, fee_id=fee_id, status=status, offset=offset, limit=limit)
