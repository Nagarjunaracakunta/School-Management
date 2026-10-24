import logging
import uuid

from app.models.academic import SchoolClass, Section, SectionSubjectTeacher, Subject, Teacher
from app.repositories.academic_repository import AcademicRepository
from app.schemas.academic import (
    AssignmentCreate,
    AssignmentOut,
    ClassCreate,
    SectionCreate,
    SectionOut,
    SubjectCreate,
    TeacherCreate,
)
from app.utils.errors import ConflictError, NotFoundError

logger = logging.getLogger(__name__)


def section_out(section: Section) -> SectionOut:
    return SectionOut(
        id=section.id,
        class_id=section.class_id,
        class_name=section.school_class.name,
        name=section.name,
        capacity=section.capacity,
    )


def assignment_out(a: SectionSubjectTeacher) -> AssignmentOut:
    return AssignmentOut(
        id=a.id,
        section_id=a.section_id,
        subject_id=a.subject_id,
        subject_name=a.subject.name,
        teacher_id=a.teacher_id,
        teacher_name=a.teacher.name,
    )


class AcademicService:
    """Classes, sections, subjects, teachers and who teaches what."""

    def __init__(self, repo: AcademicRepository) -> None:
        self.repo = repo

    def _require(self, model: type, object_id: uuid.UUID, label: str):
        obj = self.repo.get(model, object_id)
        if obj is None:
            raise NotFoundError(f"{label} not found")
        return obj

    # classes
    def create_class(self, data: ClassCreate) -> SchoolClass:
        if self.repo.class_by_name(data.name):
            raise ConflictError(f"Class '{data.name}' already exists")
        obj = SchoolClass(name=data.name)
        self.repo.add(obj)
        self.repo.commit()
        return obj

    def list_classes(self, offset: int, limit: int):
        return self.repo.page(SchoolClass, order_by=SchoolClass.name, offset=offset, limit=limit)

    # sections
    def create_section(self, data: SectionCreate) -> Section:
        self._require(SchoolClass, data.class_id, "Class")
        if self.repo.section_exists(data.class_id, data.name):
            raise ConflictError(f"Section '{data.name}' already exists in this class")
        section = Section(class_id=data.class_id, name=data.name, capacity=data.capacity)
        self.repo.add(section)
        self.repo.commit()
        return self._require(Section, section.id, "Section")

    def list_sections(self, class_id: uuid.UUID | None, offset: int, limit: int):
        where = [Section.class_id == class_id] if class_id else []
        return self.repo.page(Section, *where, order_by=Section.name, offset=offset, limit=limit)

    # subjects
    def create_subject(self, data: SubjectCreate) -> Subject:
        subject = Subject(name=data.name, code=data.code)
        self.repo.add(subject)
        self.repo.commit()  # unique name/code enforced by the database
        return subject

    def list_subjects(self, offset: int, limit: int):
        return self.repo.page(Subject, order_by=Subject.name, offset=offset, limit=limit)

    # teachers
    def create_teacher(self, data: TeacherCreate) -> Teacher:
        teacher = Teacher(name=data.name, email=str(data.email).lower(), phone=data.phone, user_id=data.user_id)
        self.repo.add(teacher)
        self.repo.commit()
        return teacher

    def list_teachers(self, offset: int, limit: int):
        return self.repo.page(Teacher, order_by=Teacher.name, offset=offset, limit=limit)

    # assignments
    def assign_teacher(self, section_id: uuid.UUID, data: AssignmentCreate) -> AssignmentOut:
        self._require(Section, section_id, "Section")
        self._require(Subject, data.subject_id, "Subject")
        self._require(Teacher, data.teacher_id, "Teacher")
        if self.repo.assignment_for(section_id, data.subject_id):
            raise ConflictError("This subject already has a teacher in this section")
        assignment = SectionSubjectTeacher(
            section_id=section_id, subject_id=data.subject_id, teacher_id=data.teacher_id
        )
        self.repo.add(assignment)
        self.repo.commit()
        logger.info("teacher assigned", extra={"section_id": str(section_id), "teacher_id": str(data.teacher_id)})
        return assignment_out(self._require(SectionSubjectTeacher, assignment.id, "Assignment"))

    def list_assignments(self, section_id: uuid.UUID) -> list[AssignmentOut]:
        self._require(Section, section_id, "Section")
        return [assignment_out(a) for a in self.repo.assignments(section_id)]
