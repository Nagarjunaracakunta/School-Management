"""Races that only a real database can show. They need PostgreSQL (row locks and unique keys across
separate connections); on the default in-memory SQLite they are skipped."""

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest

from app.models.fee import Fee, Payment
from app.repositories.fee_repository import FeeRepository
from app.repositories.payment_repository import PaymentRepository
from app.schemas.fee import PaymentCreate
from app.services.payment_service import PaymentService
from app.utils.errors import ConflictError
from app.utils.security import CurrentUser, Role

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL", "").startswith("postgresql"), reason="needs PostgreSQL"
)
THREADS = 8


@pytest.fixture
def pay_concurrently(client, students):
    """pay(fee_id, amounts_and_keys) runs one payment per thread, each in its own session, all at once."""
    session_factory = client.app.state.session_factory

    def run(fee_id: str, attempts: list[tuple[str, str]], who: str = "parent-1"):
        student_token = None  # the fake student service ignores the token's signature
        barrier = threading.Barrier(len(attempts))
        user = CurrentUser(id=who, role=Role.ADMIN, name="t", token=student_token or "")

        def one(attempt):
            amount, key = attempt
            barrier.wait()  # release every thread at the same instant
            with session_factory() as session:
                service = PaymentService(PaymentRepository(session), FeeRepository(session), _StudentsStub(students))
                try:
                    payment, created = service.pay(
                        PaymentCreate(fee_id=uuid.UUID(fee_id), amount=Decimal(amount), method="UPI"), key, user
                    )
                    return ("created" if created else "replayed", str(payment.id))
                except ConflictError as exc:
                    return ("conflict", exc.message)

        with ThreadPoolExecutor(len(attempts)) as pool:
            return list(pool.map(one, attempts))

    return run


class _StudentsStub:
    def __init__(self, fake) -> None:
        self._fake = fake

    def get_student(self, student_id, token):
        return next(iter(self._fake.students.values()))


def totals(client, fee_id):
    with client.app.state.session_factory() as session:
        fee = session.get(Fee, uuid.UUID(fee_id))
        n = session.query(Payment).filter(Payment.fee_id == fee.id).count()
        return fee.amount_paid, fee.status, n


def test_simultaneous_payments_can_never_overpay(client, make_fee, pay_concurrently):
    fee = make_fee(amount="500")
    results = pay_concurrently(fee["id"], [("100.00", f"key-race-{i:04d}") for i in range(THREADS)])

    outcomes = [r[0] for r in results]
    assert outcomes.count("created") == 5 and outcomes.count("conflict") == THREADS - 5
    paid, status, rows = totals(client, fee["id"])
    assert (paid, status, rows) == (Decimal("500.00"), "PAID", 5)  # exactly the fee, never more


def test_one_retry_storm_with_the_same_key_charges_once(client, make_fee, pay_concurrently):
    fee = make_fee(amount="1000")
    results = pay_concurrently(fee["id"], [("300.00", "storm-key-0001")] * THREADS)

    outcomes = [r[0] for r in results]
    assert outcomes.count("created") == 1 and outcomes.count("replayed") == THREADS - 1
    assert len({r[1] for r in results}) == 1  # everyone got the same payment back
    assert totals(client, fee["id"])[0] == Decimal("300.00")


def test_retry_that_arrives_after_the_fee_is_fully_paid_still_gets_the_original(client, make_fee, pay_concurrently):
    """The nastiest case: the first payment clears the whole fee, so a concurrent identical retry must be
    answered with that payment, not with 'already fully paid'."""
    fee = make_fee(amount="100")
    results = pay_concurrently(fee["id"], [("100.00", "full-pay-key-1")] * THREADS)

    assert [r[0] for r in results].count("created") == 1
    assert {r[0] for r in results} <= {"created", "replayed"}  # no 409 for a legitimate retry
    assert totals(client, fee["id"])[1:] == ("PAID", 1)


def test_the_database_itself_refuses_an_overpayment(client, make_fee):
    """Even code that bypasses all our checks cannot push amount_paid above amount_due."""
    from sqlalchemy.exc import IntegrityError

    fee = make_fee(amount="100")
    with client.app.state.session_factory() as session:
        row = session.get(Fee, uuid.UUID(fee["id"]))
        row.amount_paid = Decimal("100.01")
        with pytest.raises(IntegrityError, match="paid_within_due"):
            session.commit()
