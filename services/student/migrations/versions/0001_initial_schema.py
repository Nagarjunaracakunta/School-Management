"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-24 14:13:52.513393
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "classes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_classes")),
        sa.UniqueConstraint("name", name=op.f("uq_classes_name")),
    )
    op.create_table(
        "parents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column("relationship", sa.String(length=20), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_parents")),
    )
    op.create_index("ix_parents_email", "parents", ["email"], unique=True)
    op.create_index("ix_parents_user_id", "parents", ["user_id"], unique=False)
    op.create_table(
        "students",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("admission_ref", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("date_of_birth", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('ACTIVE', 'INACTIVE')", name=op.f("ck_students_status_valid")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_students")),
        sa.UniqueConstraint("admission_ref", name=op.f("uq_students_admission_ref")),
    )
    op.create_index("ix_students_name", "students", ["name"], unique=False)
    op.create_index("ix_students_status", "students", ["status"], unique=False)
    op.create_table(
        "subjects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_subjects")),
        sa.UniqueConstraint("code", name=op.f("uq_subjects_code")),
        sa.UniqueConstraint("name", name=op.f("uq_subjects_name")),
    )
    op.create_table(
        "teachers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_teachers")),
        sa.UniqueConstraint("email", name=op.f("uq_teachers_email")),
    )
    op.create_index("ix_teachers_user_id", "teachers", ["user_id"], unique=False)
    op.create_table(
        "sections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("class_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=20), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.CheckConstraint("capacity BETWEEN 1 AND 100", name=op.f("ck_sections_capacity_valid")),
        sa.ForeignKeyConstraint(["class_id"], ["classes.id"], name=op.f("fk_sections_class_id_classes")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sections")),
        sa.UniqueConstraint("class_id", "name", name=op.f("uq_sections_class_id_name")),
    )
    op.create_table(
        "student_parents",
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["parent_id"], ["parents.id"], name=op.f("fk_student_parents_parent_id_parents"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["student_id"], ["students.id"], name=op.f("fk_student_parents_student_id_students"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("student_id", "parent_id", name=op.f("pk_student_parents")),
    )
    op.create_table(
        "enrollments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("section_id", sa.Uuid(), nullable=False),
        sa.Column("academic_year", sa.String(length=7), nullable=False),
        sa.Column("enrolled_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["section_id"], ["sections.id"], name=op.f("fk_enrollments_section_id_sections")),
        sa.ForeignKeyConstraint(
            ["student_id"], ["students.id"], name=op.f("fk_enrollments_student_id_students"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_enrollments")),
        sa.UniqueConstraint("student_id", "academic_year", name=op.f("uq_enrollments_student_id_academic_year")),
    )
    op.create_index("ix_enrollments_section_year", "enrollments", ["section_id", "academic_year"], unique=False)
    op.create_table(
        "section_subject_teachers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("section_id", sa.Uuid(), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("teacher_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["section_id"], ["sections.id"], name=op.f("fk_section_subject_teachers_section_id_sections")
        ),
        sa.ForeignKeyConstraint(
            ["subject_id"], ["subjects.id"], name=op.f("fk_section_subject_teachers_subject_id_subjects")
        ),
        sa.ForeignKeyConstraint(
            ["teacher_id"], ["teachers.id"], name=op.f("fk_section_subject_teachers_teacher_id_teachers")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_section_subject_teachers")),
        sa.UniqueConstraint("section_id", "subject_id", name=op.f("uq_section_subject_teachers_section_id_subject_id")),
    )


def downgrade() -> None:
    op.drop_table("section_subject_teachers")
    op.drop_index("ix_enrollments_section_year", table_name="enrollments")
    op.drop_table("enrollments")
    op.drop_table("student_parents")
    op.drop_table("sections")
    op.drop_index("ix_teachers_user_id", table_name="teachers")
    op.drop_table("teachers")
    op.drop_table("subjects")
    op.drop_index("ix_students_status", table_name="students")
    op.drop_index("ix_students_name", table_name="students")
    op.drop_table("students")
    op.drop_index("ix_parents_user_id", table_name="parents")
    op.drop_index("ix_parents_email", table_name="parents")
    op.drop_table("parents")
    op.drop_table("classes")
