"""The events this service understands. Producers (Admission, Fee, Attendance) own the shape; we read only
the fields we need and ignore the rest, so a producer adding a field never breaks us."""

import datetime as dt
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict


class Envelope(BaseModel):
    event_id: uuid.UUID
    event_type: str
    version: int = 1
    occurred_at: dt.datetime
    source: str
    data: dict[str, Any]


class Parent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    email: str
    phone: str | None = None


class AdmissionData(BaseModel):
    model_config = ConfigDict(extra="ignore")

    applicant_name: str
    class_applied: str
    parents: list[Parent]


class PaymentData(BaseModel):
    model_config = ConfigDict(extra="ignore")

    receipt_no: str
    fee_name: str
    student_name: str
    amount: str
    balance_after: str
    parents: list[Parent]


class OverdueData(BaseModel):
    model_config = ConfigDict(extra="ignore")

    student_name: str
    fee_name: str
    amount_outstanding: str
    due_date: dt.date
    days_overdue: int
    parents: list[Parent]


class AbsenceData(BaseModel):
    model_config = ConfigDict(extra="ignore")

    student_name: str
    class_name: str | None = None
    section_name: str | None = None
    date: dt.date
    parents: list[Parent]
