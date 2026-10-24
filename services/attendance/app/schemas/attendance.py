import datetime as dt
import uuid
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class SubjectType(StrEnum):
    STUDENT = "student"
    TEACHER = "teacher"


class AttendanceStatus(StrEnum):
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    LATE = "LATE"


class AttendanceMark(BaseModel):
    subject_type: SubjectType = SubjectType.STUDENT
    subject_id: uuid.UUID
    date: dt.date
    status: AttendanceStatus


class BulkRecord(BaseModel):
    student_id: uuid.UUID
    status: AttendanceStatus


class BulkMark(BaseModel):
    """Mark a whole section for one day in one request (what a teacher really does each morning)."""

    section_id: uuid.UUID
    date: dt.date
    records: list[BulkRecord] = Field(min_length=1, max_length=100)

    @field_validator("records")
    @classmethod
    def _no_duplicates(cls, records: list[BulkRecord]) -> list[BulkRecord]:
        ids = [r.student_id for r in records]
        if len(ids) != len(set(ids)):
            raise ValueError("each student may appear only once")
        return records


class AttendanceOut(BaseModel):
    id: uuid.UUID
    subject_type: SubjectType
    subject_id: uuid.UUID
    subject_name: str
    class_name: str | None
    section_name: str | None
    date: dt.date
    status: AttendanceStatus
    marked_by: str
    updated_at: dt.datetime


class BulkResult(BaseModel):
    date: dt.date
    section_id: uuid.UUID
    created: int
    updated: int
    absent_notifications: int


class SummaryOut(BaseModel):
    """`present` counts everyone who attended, late arrivals included; `late` says how many of those were late."""

    date: dt.date
    present: int
    late: int
    absent: int
    total: int


class StudentReportRow(BaseModel):
    student_id: uuid.UUID
    student_name: str
    present: int
    late: int
    absent: int
    total_days: int
    attendance_percentage: float
