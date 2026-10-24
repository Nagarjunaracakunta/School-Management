from __future__ import annotations  # this class has a method called `list`; without lazy annotations Python 3.12

# would read a later `list[X]` annotation as that method instead of the builtin type
import logging
import uuid

from app.models.academic import Enrollment, Parent, Student
from app.repositories.student_repository import StudentRepository, StudentRow
from app.schemas.student import (
    EnrollmentCreate,
    EnrollmentOut,
    ParentOut,
    StudentCreate,
    StudentOut,
    StudentStatus,
    StudentUpdate,
)
from app.utils.errors import ConflictError, NotFoundError
from app.utils.security import CurrentUser

logger = logging.getLogger(__name__)


def student_out(row: StudentRow) -> StudentOut:
    student, class_name, section_name = row
    return StudentOut(
        id=student.id,
        admission_ref=student.admission_ref,
        name=student.name,
        date_of_birth=student.date_of_birth,
        status=StudentStatus(student.status),
        class_name=class_name,
        section_name=section_name,
        parents=[ParentOut.model_validate(p) for p in student.parents],
    )


def enrollment_out(e: Enrollment) -> EnrollmentOut:
    return EnrollmentOut(
        id=e.id,
        student_id=e.student_id,
        section_id=e.section_id,
        class_name=e.section.school_class.name,
        section_name=e.section.name,
        academic_year=e.academic_year,
        enrolled_at=e.enrolled_at,
    )


class StudentService:
    def __init__(self, repo: StudentRepository) -> None:
        self.repo = repo
        self.academic_year = repo.academic_year

    def create(self, data: StudentCreate, admin: CurrentUser) -> tuple[StudentOut, bool]:
        """Returns (student, created). Repeating the same admission returns the existing student."""
        if data.admission_ref:
            existing = self.repo.student_by_admission(data.admission_ref)
            if existing:
                return self.get(existing.id, admin), False

        parents: list[Parent] = []
        for index, p in enumerate(data.parents):
            email = str(p.email).lower()
            # Siblings share one parent record, matched by email
            parent = self.repo.parent_by_email(email) or Parent(
                name=p.name, email=email, phone=p.phone, relationship_type=p.relationship
            )
            if index == 0 and data.guardian_user_id and parent.user_id is None:
                parent.user_id = data.guardian_user_id
            parents.append(parent)

        student = Student(
            name=data.name, date_of_birth=data.date_of_birth, admission_ref=data.admission_ref, parents=parents
        )
        self.repo.add(student)
        self.repo.commit()
        logger.info("student created", extra={"student_id": str(student.id)})
        return student_out((student, None, None)), True

    def get(self, student_id: uuid.UUID, user: CurrentUser) -> StudentOut:
        rows, _ = self.repo.search(user, student_id=student_id, limit=1)
        # Not visible and not existing look the same on purpose
        if not rows:
            raise NotFoundError("Student not found")
        return student_out(rows[0])

    def list(self, user: CurrentUser, *, page: int, page_size: int, **filters) -> tuple[list[StudentOut], int]:
        rows, total = self.repo.search(user, offset=(page - 1) * page_size, limit=page_size, **filters)
        return [student_out(r) for r in rows], total

    def update(self, student_id: uuid.UUID, data: StudentUpdate, admin: CurrentUser) -> StudentOut:
        student = self.repo.get(Student, student_id)
        if student is None:
            raise NotFoundError("Student not found")
        for field, value in data.model_dump(exclude_unset=True, exclude_none=True).items():
            setattr(student, field, value.value if isinstance(value, StudentStatus) else value)
        self.repo.commit()
        return self.get(student_id, admin)

    def enroll(self, student_id: uuid.UUID, data: EnrollmentCreate) -> EnrollmentOut:
        if self.repo.get(Student, student_id) is None:
            raise NotFoundError("Student not found")
        section = self.repo.lock_section(data.section_id)  # held until commit: see lock_section()
        if section is None:
            raise NotFoundError("Section not found")
        year = data.academic_year or self.academic_year
        if self.repo.enrollment_for_year(student_id, year):
            raise ConflictError(f"Student is already enrolled for {year}")
        if self.repo.enrollment_count(section.id, year) >= section.capacity:
            raise ConflictError(f"Section {section.school_class.name}-{section.name} is full ({section.capacity})")
        enrollment = Enrollment(student_id=student_id, section_id=section.id, academic_year=year)
        self.repo.add(enrollment)
        self.repo.commit()
        logger.info("student enrolled", extra={"student_id": str(student_id), "section_id": str(section.id)})
        return enrollment_out(enrollment)

    def enrollments(self, student_id: uuid.UUID, user: CurrentUser) -> list[EnrollmentOut]:
        self.get(student_id, user)  # applies the same visibility rules
        return [enrollment_out(e) for e in self.repo.enrollments(student_id)]
