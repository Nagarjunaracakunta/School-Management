import re
import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, Field, PlainSerializer, StringConstraints, field_validator

Money = Annotated[Decimal, Field(gt=0, max_digits=10, decimal_places=2)]


# Output money is always a string with exactly 2 decimals ("15000.00"), whether the value was just
# created in memory or re-read from the database. Strings also avoid float rounding in JSON.
def money_str(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01")), "f")


MoneyOut = Annotated[Decimal, PlainSerializer(money_str, return_type=str, when_used="json")]
YEAR_RE = re.compile(r"^\d{4}-\d{2}$")


class FeeStatus(StrEnum):
    PENDING = "PENDING"
    PARTIAL = "PARTIAL"
    PAID = "PAID"
    OVERDUE = "OVERDUE"  # derived: unpaid and past its due date. Never stored.


class PaymentMethod(StrEnum):
    CARD = "CARD"
    UPI = "UPI"
    CASH = "CASH"


class FeeStructureCreate(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    class_id: uuid.UUID
    academic_year: str
    amount: Money
    due_date: date

    @field_validator("academic_year")
    @classmethod
    def _year(cls, v: str) -> str:
        if not YEAR_RE.match(v):
            raise ValueError("academic_year must look like 2026-27")
        return v


class FeeStructureOut(BaseModel):
    id: uuid.UUID
    name: str
    class_id: uuid.UUID
    class_name: str
    academic_year: str
    amount: MoneyOut
    due_date: date


class FeeAssign(BaseModel):
    student_id: uuid.UUID
    structure_id: uuid.UUID
    amount: Money | None = None  # optional per-student override (e.g. a scholarship)


class FeeOut(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    student_name: str
    structure_id: uuid.UUID
    name: str
    amount_due: MoneyOut
    amount_paid: MoneyOut
    outstanding: MoneyOut
    due_date: date
    status: FeeStatus


class PaymentCreate(BaseModel):
    fee_id: uuid.UUID
    amount: Money
    method: PaymentMethod


class PaymentOut(BaseModel):
    id: uuid.UUID
    receipt_no: str
    fee_id: uuid.UUID
    student_id: uuid.UUID
    amount: MoneyOut
    method: PaymentMethod
    status: str
    balance_after: MoneyOut
    created_at: datetime


class ReceiptOut(BaseModel):
    receipt_no: str
    issued_at: datetime
    student_name: str
    fee_name: str
    amount_paid: MoneyOut
    payment_method: PaymentMethod
    balance_after: MoneyOut
