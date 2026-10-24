import re
import uuid
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    field_validator,
)

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
PHONE_RE = re.compile(r"^\+?[0-9][0-9 \-]{6,18}$")
YEAR_RE = re.compile(r"^\d{4}-\d{2}$")


class StudentStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class Relationship(StrEnum):
    FATHER = "FATHER"
    MOTHER = "MOTHER"
    GUARDIAN = "GUARDIAN"


def _check_dob(v: date) -> date:
    age = (datetime.now(UTC).date() - v).days / 365.25
    if not 2 <= age <= 25:
        raise ValueError("date_of_birth must be a plausible school-age date (2 to 25 years ago)")
    return v


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


class StudentCreate(BaseModel):
    name: Name
    date_of_birth: date
    parents: list[ParentIn] = Field(min_length=1, max_length=3)
    # Set when the student comes from an approved admission (makes creation idempotent)
    admission_ref: uuid.UUID | None = None
    # Login account to link to the FIRST parent so that parent can see the child
    guardian_user_id: Annotated[str, StringConstraints(max_length=64)] | None = None

    _dob = field_validator("date_of_birth")(_check_dob)


class StudentUpdate(BaseModel):
    name: Name | None = None
    date_of_birth: date | None = None
    status: StudentStatus | None = None

    @field_validator("date_of_birth")
    @classmethod
    def _dob(cls, v: date | None) -> date | None:
        return _check_dob(v) if v else v


class StudentOut(BaseModel):
    id: uuid.UUID
    admission_ref: uuid.UUID | None
    name: str
    date_of_birth: date
    status: StudentStatus
    class_name: str | None  # for the current academic year
    section_name: str | None
    parents: list[ParentOut]


class EnrollmentCreate(BaseModel):
    section_id: uuid.UUID
    academic_year: str | None = None  # defaults to the current academic year

    @field_validator("academic_year")
    @classmethod
    def _year(cls, v: str | None) -> str | None:
        if v is not None and not YEAR_RE.match(v):
            raise ValueError("academic_year must look like 2026-27")
        return v


class EnrollmentOut(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    section_id: uuid.UUID
    class_name: str
    section_name: str
    academic_year: str
    enrolled_at: datetime
