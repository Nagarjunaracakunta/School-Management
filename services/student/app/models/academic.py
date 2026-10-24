import uuid
from datetime import UTC, date, datetime

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


# Many-to-many: siblings share a parent; a student can have two parents/guardians.
student_parents = Table(
    "student_parents",
    Base.metadata,
    Column("student_id", ForeignKey("students.id", ondelete="CASCADE"), primary_key=True),
    Column("parent_id", ForeignKey("parents.id", ondelete="CASCADE"), primary_key=True),
)


class Parent(Base):
    __tablename__ = "parents"
    __table_args__ = (Index("ix_parents_email", "email", unique=True), Index("ix_parents_user_id", "user_id"))

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(254))
    phone: Mapped[str] = mapped_column(String(20))
    relationship_type: Mapped[str] = mapped_column("relationship", String(20), default="GUARDIAN")
    # The login account (Auth Service user id) allowed to see this parent's children. No FK: Auth owns users.
    user_id: Mapped[str | None] = mapped_column(String(64))


class Student(Base):
    __tablename__ = "students"
    __table_args__ = (
        Index("ix_students_name", "name"),
        Index("ix_students_status", "status"),
        CheckConstraint("status IN ('ACTIVE', 'INACTIVE')", name="status_valid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Which admission created this student. Unique => enrolling twice cannot create duplicates.
    admission_ref: Mapped[uuid.UUID | None] = mapped_column(Uuid, unique=True)
    name: Mapped[str] = mapped_column(String(120))
    date_of_birth: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(10), default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    parents: Mapped[list[Parent]] = relationship(secondary=student_parents, lazy="selectin")


class SchoolClass(Base):
    __tablename__ = "classes"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(50), unique=True)


class Section(Base):
    __tablename__ = "sections"
    __table_args__ = (
        UniqueConstraint("class_id", "name"),
        CheckConstraint("capacity BETWEEN 1 AND 100", name="capacity_valid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    class_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("classes.id"))
    name: Mapped[str] = mapped_column(String(20))
    capacity: Mapped[int] = mapped_column(Integer, default=40)

    school_class: Mapped[SchoolClass] = relationship(lazy="joined")


class Subject(Base):
    __tablename__ = "subjects"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)


class Teacher(Base):
    __tablename__ = "teachers"
    __table_args__ = (Index("ix_teachers_user_id", "user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(254), unique=True)
    phone: Mapped[str] = mapped_column(String(20))
    user_id: Mapped[str | None] = mapped_column(String(64))  # login account, see Parent.user_id


class SectionSubjectTeacher(Base):
    """Teacher assignment: who teaches which subject in which section."""

    __tablename__ = "section_subject_teachers"
    __table_args__ = (UniqueConstraint("section_id", "subject_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    section_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sections.id"))
    subject_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("subjects.id"))
    teacher_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("teachers.id"))

    subject: Mapped[Subject] = relationship(lazy="joined")
    teacher: Mapped[Teacher] = relationship(lazy="joined")


class Enrollment(Base):
    __tablename__ = "enrollments"
    __table_args__ = (
        UniqueConstraint("student_id", "academic_year"),  # one section per student per year
        Index("ix_enrollments_section_year", "section_id", "academic_year"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"))
    section_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sections.id"))
    academic_year: Mapped[str] = mapped_column(String(7))
    enrolled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    section: Mapped[Section] = relationship(lazy="joined")
