import re
import uuid
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints, field_validator, model_validator

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
PHONE_RE = re.compile(r"^\+?[0-9][0-9 \-]{6,18}$")


class AdmissionStatus(StrEnum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ENROLLED = "ENROLLED"  # set by the enrollment step added in the Student phase


class Relationship(StrEnum):
    FATHER = "FATHER"
    MOTHER = "MOTHER"
    GUARDIAN = "GUARDIAN"


class ParentIn(BaseModel):
    name: Name
    email: EmailStr
    phone: str
    relationship: Relationship = Relationship.GUARDIAN

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        v = v.strip()
        if not PHONE_RE.match(v):
            raise ValueError("phone must be 7-15 digits, optionally starting with +")
        return v


class ParentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    email: str
    phone: str
    relationship: str = Field(validation_alias="relationship_type")


class AdmissionCreate(BaseModel):
    applicant_name: Name
    date_of_birth: date
    class_applied: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
    parents: list[ParentIn] = Field(min_length=1, max_length=3)

    @field_validator("date_of_birth")
    @classmethod
    def _plausible_age(cls, v: date) -> date:
        age = (datetime.now(UTC).date() - v).days / 365.25
        if not 2 <= age <= 25:
            raise ValueError("date_of_birth must be a plausible school-age date (2 to 25 years ago)")
        return v


class AdmissionUpdate(BaseModel):
    """Admin review. Only these fields can change; applicant data is immutable after submission."""

    status: AdmissionStatus | None = None
    review_notes: Annotated[str, StringConstraints(max_length=1000)] | None = None

    @model_validator(mode="after")
    def _something_to_change(self) -> "AdmissionUpdate":
        if self.status is None and self.review_notes is None:
            raise ValueError("provide status and/or review_notes")
        return self


class AdmissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    applicant_name: str
    date_of_birth: date
    class_applied: str
    status: AdmissionStatus
    review_notes: str | None
    student_id: uuid.UUID | None
    submitted_at: datetime
    updated_at: datetime
    parents: list[ParentOut]
