import uuid
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints, field_validator

from app.schemas.student import PHONE_RE

Short = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]


class ClassCreate(BaseModel):
    name: Short


class ClassOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str


class SectionCreate(BaseModel):
    class_id: uuid.UUID
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]
    capacity: int = Field(default=40, ge=1, le=100)


class SectionOut(BaseModel):
    id: uuid.UUID
    class_id: uuid.UUID
    class_name: str
    name: str
    capacity: int


class SubjectCreate(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    code: Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^[A-Za-z0-9]{2,20}$")]


class SubjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    code: str


class TeacherCreate(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    email: EmailStr
    phone: str
    user_id: Annotated[str, StringConstraints(max_length=64)] | None = None

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        v = v.strip()
        if not PHONE_RE.match(v):
            raise ValueError("phone must be 7-15 digits, optionally starting with +")
        return v


class TeacherOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    email: str
    phone: str
    user_id: str | None


class AssignmentCreate(BaseModel):
    subject_id: uuid.UUID
    teacher_id: uuid.UUID


class AssignmentOut(BaseModel):
    id: uuid.UUID
    section_id: uuid.UUID
    subject_id: uuid.UUID
    subject_name: str
    teacher_id: uuid.UUID
    teacher_name: str
