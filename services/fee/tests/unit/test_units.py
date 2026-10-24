import re
from datetime import date, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.models.fee import Fee
from app.schemas.fee import FeeStatus, FeeStructureCreate, PaymentCreate
from app.services.fee_service import effective_status
from app.services.payment_service import new_receipt_no

FEE_ID = "00000000-0000-0000-0000-000000000001"


@pytest.mark.parametrize("amount", ["0", "-5", "10.123", "abc", "123456789012"])
def test_bad_amounts_are_rejected(amount):
    with pytest.raises(ValidationError):
        PaymentCreate(fee_id=FEE_ID, amount=amount, method="UPI")


def test_money_is_exact_decimal():
    assert PaymentCreate(fee_id=FEE_ID, amount="0.10", method="CASH").amount + Decimal("0.20") == Decimal("0.30")


def test_unknown_method_rejected():
    with pytest.raises(ValidationError):
        PaymentCreate(fee_id=FEE_ID, amount="5", method="BITCOIN")


def test_structure_year_format():
    with pytest.raises(ValidationError):
        FeeStructureCreate(name="x", class_id=FEE_ID, academic_year="2026", amount="1", due_date=date.today())


def test_effective_status_rules():
    today = date.today()
    fee = Fee(amount_due=Decimal("100"), amount_paid=Decimal("0"), status="PENDING", due_date=today)
    assert effective_status(fee, today) is FeeStatus.PENDING  # due today is not yet overdue
    fee.due_date = today - timedelta(days=1)
    assert effective_status(fee, today) is FeeStatus.OVERDUE
    fee.status = "PARTIAL"
    assert effective_status(fee, today) is FeeStatus.OVERDUE
    fee.status = "PAID"
    assert effective_status(fee, today) is FeeStatus.PAID  # paid fees are never overdue
    assert fee.outstanding == Decimal("100")


def test_receipt_number_format_and_uniqueness():
    numbers = {new_receipt_no() for _ in range(200)}
    assert len(numbers) == 200 and all(re.fullmatch(r"RCT-\d{8}-[0-9A-F]{8}", n) for n in numbers)
