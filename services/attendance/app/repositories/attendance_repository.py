import datetime as dt
import uuid
from typing import Any

from sqlalchemy import case, func, select

from app.models.attendance import Attendance
from app.repositories.outbox_repository import OutboxRepository


class AttendanceRepository(OutboxRepository):
    def get_record(self, subject_type: str, subject_id: uuid.UUID, day: dt.date) -> Attendance | None:
        return self.session.scalar(
            select(Attendance).where(
                Attendance.subject_type == subject_type,
                Attendance.subject_id == subject_id,
                Attendance.attendance_date == day,
            )
        )

    def records_for_day(
        self, subject_type: str, subject_ids: list[uuid.UUID], day: dt.date
    ) -> dict[uuid.UUID, Attendance]:
        rows = self.session.scalars(
            select(Attendance).where(
                Attendance.subject_type == subject_type,
                Attendance.subject_id.in_(subject_ids),
                Attendance.attendance_date == day,
            )
        )
        return {r.subject_id: r for r in rows}

    @staticmethod
    def _filters(
        *,
        subject_type: str | None,
        subject_ids: list[uuid.UUID] | None,
        status: str | None = None,
        day: dt.date | None = None,
        date_from: dt.date | None = None,
        date_to: dt.date | None = None,
        class_name: str | None = None,
        section_name: str | None = None,
    ) -> list[Any]:
        """`subject_ids=None` means unrestricted (admin); a list restricts to those people."""
        where: list[Any] = []
        if subject_type:
            where.append(Attendance.subject_type == subject_type)
        if subject_ids is not None:
            where.append(Attendance.subject_id.in_(subject_ids))
        if status:
            where.append(Attendance.status == status)
        if day:
            where.append(Attendance.attendance_date == day)
        if date_from:
            where.append(Attendance.attendance_date >= date_from)
        if date_to:
            where.append(Attendance.attendance_date <= date_to)
        if class_name:
            where.append(Attendance.class_name == class_name)
        if section_name:
            where.append(Attendance.section_name == section_name)
        return where

    def search(self, *, offset: int, limit: int, **filters: Any) -> tuple[list[Attendance], int]:
        where = self._filters(**filters)
        total = self.session.scalar(select(func.count(Attendance.id)).where(*where)) or 0
        rows = self.session.scalars(
            select(Attendance)
            .where(*where)
            .order_by(Attendance.attendance_date.desc(), Attendance.subject_name, Attendance.id)
            .offset(offset)
            .limit(limit)
        )
        return list(rows), total

    def day_counts(self, **filters: Any) -> dict[str, int]:
        where = self._filters(**filters)
        rows = self.session.execute(
            select(Attendance.status, func.count(Attendance.id)).where(*where).group_by(Attendance.status)
        )
        return dict(rows.all())

    def student_report(self, *, offset: int, limit: int, **filters: Any) -> tuple[list[Any], int]:
        """One row per student with counts per status over the filtered date range."""
        where = self._filters(subject_type="student", **filters)

        def count(status: str):
            return func.coalesce(func.sum(case((Attendance.status == status, 1), else_=0)), 0)

        grouped = (
            select(
                Attendance.subject_id,
                func.max(Attendance.subject_name).label("name"),
                count("PRESENT").label("present"),
                count("LATE").label("late"),
                count("ABSENT").label("absent"),
                func.count(Attendance.id).label("total"),
            )
            .where(*where)
            .group_by(Attendance.subject_id)
        )
        total = self.session.scalar(select(func.count()).select_from(grouped.subquery())) or 0
        rows = self.session.execute(grouped.order_by(func.max(Attendance.subject_name)).offset(offset).limit(limit))
        return list(rows.all()), total
