from __future__ import annotations  # this class has a method called `list`; without lazy annotations Python 3.12

# would read a later `list[X]` annotation as that method instead of the builtin type
import datetime as dt
import logging
import uuid
from collections.abc import Callable

from app.clients.student_client import StudentClient
from app.models.attendance import Attendance
from app.repositories.attendance_repository import AttendanceRepository
from app.schemas.attendance import (
    AttendanceMark,
    AttendanceOut,
    AttendanceStatus,
    BulkMark,
    BulkResult,
    StudentReportRow,
    SubjectType,
    SummaryOut,
)
from app.services.access import visible_student_ids
from app.utils.errors import ConflictError, ForbiddenError, NotFoundError, UnprocessableError
from app.utils.security import CurrentUser, Role

logger = logging.getLogger(__name__)
MAX_REPORT_DAYS = 366


def attendance_out(a: Attendance) -> AttendanceOut:
    return AttendanceOut(
        id=a.id,
        subject_type=SubjectType(a.subject_type),
        subject_id=a.subject_id,
        subject_name=a.subject_name,
        class_name=a.class_name,
        section_name=a.section_name,
        date=a.attendance_date,
        status=AttendanceStatus(a.status),
        marked_by=a.marked_by,
        updated_at=a.updated_at,
    )


class AttendanceService:
    def __init__(
        self,
        repo: AttendanceRepository,
        students: StudentClient,
        edit_window_days: int,
        clock: Callable[[], dt.date] = dt.date.today,
    ) -> None:
        self.repo = repo
        self.students = students
        self.edit_window_days = edit_window_days
        self.today = clock

    # --- marking -------------------------------------------------------------------------
    def mark(self, data: AttendanceMark, user: CurrentUser) -> tuple[AttendanceOut, bool]:
        """Returns (record, created). Marking the same day again corrects the existing record."""
        self._check_date(data.date, user)
        parents: list[dict] = []
        if data.subject_type is SubjectType.TEACHER:
            if user.role is not Role.ADMIN:
                raise ForbiddenError("Only an admin can mark teacher attendance")
            teacher = self._find_teacher(data.subject_id, user)
            name, class_name, section_name = teacher["name"], None, None
        else:
            student = self.students.get_student(str(data.subject_id), user.token)  # 404 if not yours
            if student["status"] != "ACTIVE":
                raise ConflictError("Attendance can only be marked for ACTIVE students")
            name, class_name, section_name = student["name"], student["class_name"], student["section_name"]
            parents = student["parents"]

        existing = self.repo.get_record(data.subject_type.value, data.subject_id, data.date)
        record, newly_absent = self._apply(
            existing, data.subject_type, data.subject_id, name, class_name, section_name, data.date, data.status, user
        )
        if newly_absent:
            self._queue_absence(record, parents)
        self.repo.commit()
        logger.info(
            "attendance marked",
            extra={"subject_id": str(data.subject_id), "date": data.date.isoformat(), "status": data.status.value},
        )
        return attendance_out(record), existing is None

    def mark_bulk(self, data: BulkMark, user: CurrentUser) -> BulkResult:
        self._check_date(data.date, user)
        # The roster comes from the Student Service filtered by what THIS user may see, so a teacher
        # can only mark sections they teach, and no student can be marked in the wrong section.
        roster = {uuid.UUID(s["id"]): s for s in self.students.list_section_students(str(data.section_id), user.token)}
        strangers = [str(r.student_id) for r in data.records if r.student_id not in roster]
        if strangers:
            raise UnprocessableError(
                "Some students are not in this section (or you may not mark them)", details={"student_ids": strangers}
            )

        existing = self.repo.records_for_day("student", [r.student_id for r in data.records], data.date)
        created = updated = notified = 0
        for item in data.records:
            student = roster[item.student_id]
            record, newly_absent = self._apply(
                existing.get(item.student_id),
                SubjectType.STUDENT,
                item.student_id,
                student["name"],
                student["class_name"],
                student["section_name"],
                data.date,
                item.status,
                user,
            )
            created, updated = (created + 1, updated) if item.student_id not in existing else (created, updated + 1)
            if newly_absent:
                self._queue_absence(record, student["parents"])
                notified += 1
        self.repo.commit()  # the whole class is saved or none of it
        logger.info(
            "attendance marked in bulk",
            extra={"section_id": str(data.section_id), "date": data.date.isoformat(), "count": len(data.records)},
        )
        return BulkResult(
            date=data.date, section_id=data.section_id, created=created, updated=updated, absent_notifications=notified
        )

    # --- reading -------------------------------------------------------------------------
    def list(
        self,
        user: CurrentUser,
        *,
        subject_type: SubjectType | None,
        status: AttendanceStatus | None,
        date_from: dt.date | None,
        date_to: dt.date | None,
        offset: int,
        limit: int,
    ) -> tuple[list[AttendanceOut], int]:
        scope = self._scope(user, subject_type)
        if scope is None:
            return [], 0
        rows, total = self.repo.search(
            offset=offset,
            limit=limit,
            status=status.value if status else None,
            date_from=date_from,
            date_to=date_to,
            **scope,
        )
        return [attendance_out(r) for r in rows], total

    def for_student(
        self,
        student_id: uuid.UUID,
        user: CurrentUser,
        *,
        date_from: dt.date | None,
        date_to: dt.date | None,
        offset: int,
        limit: int,
    ) -> tuple[list[AttendanceOut], int]:
        self.students.get_student(str(student_id), user.token)  # 404 if the caller may not see this child
        rows, total = self.repo.search(
            offset=offset,
            limit=limit,
            subject_type="student",
            subject_ids=[student_id],
            date_from=date_from,
            date_to=date_to,
        )
        return [attendance_out(r) for r in rows], total

    def for_teacher(
        self,
        teacher_id: uuid.UUID,
        user: CurrentUser,
        *,
        date_from: dt.date | None,
        date_to: dt.date | None,
        offset: int,
        limit: int,
    ) -> tuple[list[AttendanceOut], int]:
        teacher = self._find_teacher(teacher_id, user)
        if user.role is Role.TEACHER and teacher.get("user_id") != user.id:
            raise NotFoundError("Teacher not found")  # a teacher may read only their own record
        rows, total = self.repo.search(
            offset=offset,
            limit=limit,
            subject_type="teacher",
            subject_ids=[teacher_id],
            date_from=date_from,
            date_to=date_to,
        )
        return [attendance_out(r) for r in rows], total

    def summary(self, day: dt.date, user: CurrentUser) -> SummaryOut:
        scope = self._scope(user, SubjectType.STUDENT)
        counts = self.repo.day_counts(day=day, **scope) if scope is not None else {}
        present, late, absent = counts.get("PRESENT", 0), counts.get("LATE", 0), counts.get("ABSENT", 0)
        return SummaryOut(date=day, present=present + late, late=late, absent=absent, total=present + late + absent)

    def report(
        self,
        user: CurrentUser,
        *,
        date_from: dt.date,
        date_to: dt.date,
        class_name: str | None,
        section_name: str | None,
        offset: int,
        limit: int,
    ) -> tuple[list[StudentReportRow], int]:
        if date_to < date_from:
            raise UnprocessableError("date_to must not be before date_from")
        if (date_to - date_from).days >= MAX_REPORT_DAYS:
            raise UnprocessableError(f"Report range is limited to {MAX_REPORT_DAYS} days")
        scope = self._scope(user, SubjectType.STUDENT)
        if scope is None:
            return [], 0
        rows, total = self.repo.student_report(
            offset=offset,
            limit=limit,
            subject_ids=scope["subject_ids"],
            date_from=date_from,
            date_to=date_to,
            class_name=class_name,
            section_name=section_name,
        )
        return [
            StudentReportRow(
                student_id=r.subject_id,
                student_name=r.name,
                present=r.present,
                late=r.late,
                absent=r.absent,
                total_days=r.total,
                # Late still counts as attending; only ABSENT lowers the percentage
                attendance_percentage=round((r.present + r.late) / r.total * 100, 1),
            )
            for r in rows
        ], total

    # --- helpers -------------------------------------------------------------------------
    def _check_date(self, day: dt.date, user: CurrentUser) -> None:
        today = self.today()
        if day > today:
            raise UnprocessableError("Attendance cannot be marked for a future date")
        if user.role is not Role.ADMIN and (today - day).days > self.edit_window_days:
            raise ForbiddenError(
                f"Teachers can only mark attendance up to {self.edit_window_days} days back; ask an admin"
            )

    def _scope(self, user: CurrentUser, subject_type: SubjectType | None) -> dict | None:
        """What the caller may read, as repository filters. None = nothing visible at all."""
        if user.role is Role.ADMIN:
            return {"subject_type": subject_type.value if subject_type else None, "subject_ids": None}
        # Teachers and parents only ever see students the Student Service says they may see
        if subject_type is SubjectType.TEACHER:
            return None
        ids = visible_student_ids(self.students, user)
        if not ids:
            return None
        return {"subject_type": "student", "subject_ids": ids}

    def _find_teacher(self, teacher_id: uuid.UUID, user: CurrentUser) -> dict:
        for teacher in self.students.list_teachers(user.token):
            if teacher["id"] == str(teacher_id):
                return teacher
        raise NotFoundError("Teacher not found")

    def _apply(
        self,
        existing: Attendance | None,
        subject_type: SubjectType,
        subject_id: uuid.UUID,
        name: str,
        class_name: str | None,
        section_name: str | None,
        day: dt.date,
        status: AttendanceStatus,
        user: CurrentUser,
    ) -> tuple[Attendance, bool]:
        """Insert or correct one record. Returns (record, newly_absent)."""
        previous = existing.status if existing else None
        if existing:
            existing.status = status.value
            existing.marked_by = user.id
            record = existing
        else:
            record = Attendance(
                subject_type=subject_type.value,
                subject_id=subject_id,
                subject_name=name,
                class_name=class_name,
                section_name=section_name,
                attendance_date=day,
                status=status.value,
                marked_by=user.id,
            )
            self.repo.add(record)
        # Notify the parents only when the child BECOMES absent. Re-saving the same ABSENT does not
        # send a second message. (PRESENT -> ABSENT -> PRESENT -> ABSENT does notify again.)
        newly_absent = (
            subject_type is SubjectType.STUDENT and status is AttendanceStatus.ABSENT and previous != "ABSENT"
        )
        return record, newly_absent

    def _queue_absence(self, record: Attendance, parents: list[dict]) -> None:
        self.repo.add_event(
            "attendance.absent",
            {
                "student_id": str(record.subject_id),
                "student_name": record.subject_name,
                "class_name": record.class_name,
                "section_name": record.section_name,
                "date": record.attendance_date.isoformat(),
                "parents": [{"name": p["name"], "email": p["email"], "phone": p["phone"]} for p in parents],
            },
        )
