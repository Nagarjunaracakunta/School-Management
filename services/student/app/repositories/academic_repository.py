import uuid

from sqlalchemy import select

from app.models.academic import SchoolClass, Section, SectionSubjectTeacher
from app.repositories.base import BaseRepository


class AcademicRepository(BaseRepository):
    """Reference data: classes, sections, subjects, teachers, teacher assignments."""

    def class_by_name(self, name: str) -> SchoolClass | None:
        return self.session.scalar(select(SchoolClass).where(SchoolClass.name == name))

    def section_exists(self, class_id: uuid.UUID, name: str) -> bool:
        return (
            self.session.scalar(select(Section.id).where(Section.class_id == class_id, Section.name == name))
            is not None
        )

    def assignment_for(self, section_id: uuid.UUID, subject_id: uuid.UUID) -> SectionSubjectTeacher | None:
        return self.session.scalar(
            select(SectionSubjectTeacher).where(
                SectionSubjectTeacher.section_id == section_id, SectionSubjectTeacher.subject_id == subject_id
            )
        )

    def assignments(self, section_id: uuid.UUID) -> list[SectionSubjectTeacher]:
        rows = self.session.scalars(select(SectionSubjectTeacher).where(SectionSubjectTeacher.section_id == section_id))
        return list(rows.unique())
