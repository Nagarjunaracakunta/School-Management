import uuid
from typing import Any

from sqlalchemy import and_, func, select, true

from app.models.academic import (
    Enrollment,
    Parent,
    SchoolClass,
    Section,
    SectionSubjectTeacher,
    Student,
    Teacher,
    student_parents,
)
from app.repositories.base import BaseRepository
from app.utils.security import CurrentUser, Role

StudentRow = tuple[Student, str | None, str | None]  # student, class name, section name


class StudentRepository(BaseRepository):
    def __init__(self, session, academic_year: str) -> None:
        super().__init__(session)
        self.academic_year = academic_year

    # --- who may see which students -------------------------------------------------
    @staticmethod
    def _visible_to(user: CurrentUser) -> Any:
        """The SQL form of the access rules, so a forbidden row is never even loaded."""
        if user.role is Role.ADMIN:
            return true()
        if user.role is Role.PARENT:
            own_children = (
                select(student_parents.c.student_id)
                .join(Parent, Parent.id == student_parents.c.parent_id)
                .where(Parent.user_id == user.id)
            )
            return Student.id.in_(own_children)
        # Teacher: students enrolled (this year) in a section they are assigned to teach
        my_sections = (
            select(SectionSubjectTeacher.section_id)
            .join(Teacher, Teacher.id == SectionSubjectTeacher.teacher_id)
            .where(Teacher.user_id == user.id)
        )
        return Enrollment.section_id.in_(my_sections)

    def _join_current_placement(self, stmt):
        return (
            stmt.outerjoin(
                Enrollment,
                and_(Enrollment.student_id == Student.id, Enrollment.academic_year == self.academic_year),
            )
            .outerjoin(Section, Section.id == Enrollment.section_id)
            .outerjoin(SchoolClass, SchoolClass.id == Section.class_id)
        )

    def search(
        self,
        user: CurrentUser,
        *,
        student_id: uuid.UUID | None = None,
        status: str | None = None,
        class_id: uuid.UUID | None = None,
        section_id: uuid.UUID | None = None,
        name: str | None = None,
        admission_ref: uuid.UUID | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[StudentRow], int]:
        conditions: list[Any] = [self._visible_to(user)]
        if student_id:
            conditions.append(Student.id == student_id)
        if status:
            conditions.append(Student.status == status)
        if class_id:
            conditions.append(Section.class_id == class_id)
        if section_id:
            conditions.append(Enrollment.section_id == section_id)
        if admission_ref:
            conditions.append(Student.admission_ref == admission_ref)
        if name:
            escaped = name.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            conditions.append(Student.name.ilike(f"%{escaped}%", escape="\\"))

        total = (
            self.session.scalar(self._join_current_placement(select(func.count(Student.id))).where(*conditions)) or 0
        )
        stmt = self._join_current_placement(
            select(Student, SchoolClass.name.label("class_name"), Section.name.label("section_name"))
        )
        rows = self.session.execute(
            stmt.where(*conditions).order_by(Student.name, Student.id).offset(offset).limit(limit)
        ).all()
        return [(r[0], r[1], r[2]) for r in rows], total

    # --- writes ---------------------------------------------------------------------
    def student_by_admission(self, admission_ref: uuid.UUID) -> Student | None:
        return self.session.scalar(select(Student).where(Student.admission_ref == admission_ref))

    def parent_by_email(self, email: str) -> Parent | None:
        return self.session.scalar(select(Parent).where(Parent.email == email))

    def lock_section(self, section_id: uuid.UUID) -> Section | None:
        """Row lock on the section: simultaneous enrollments into it are handled one after another, so the
        capacity check below cannot be fooled by two requests that both see 'one seat left'.
        `of=Section` locks only this row, not the class row that is joined in with it."""
        return self.session.scalar(
            select(Section)
            .where(Section.id == section_id)
            .with_for_update(of=Section)
            .execution_options(populate_existing=True)
        )

    def enrollment_count(self, section_id: uuid.UUID, academic_year: str) -> int:
        return (
            self.session.scalar(
                select(func.count(Enrollment.id)).where(
                    Enrollment.section_id == section_id, Enrollment.academic_year == academic_year
                )
            )
            or 0
        )

    def enrollment_for_year(self, student_id: uuid.UUID, academic_year: str) -> Enrollment | None:
        return self.session.scalar(
            select(Enrollment).where(Enrollment.student_id == student_id, Enrollment.academic_year == academic_year)
        )

    def enrollments(self, student_id: uuid.UUID) -> list[Enrollment]:
        rows = self.session.scalars(
            select(Enrollment).where(Enrollment.student_id == student_id).order_by(Enrollment.academic_year.desc())
        )
        return list(rows.unique())
