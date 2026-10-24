"""Needs PostgreSQL: skipped on the default in-memory SQLite."""

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.repositories.student_repository import StudentRepository
from app.schemas.student import EnrollmentCreate
from app.services.student_service import StudentService
from app.utils.errors import ConflictError

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL", "").startswith("postgresql"), reason="needs PostgreSQL"
)


def test_a_full_section_cannot_be_overfilled_by_simultaneous_enrollments(client, admin, make_student, make_section):
    section = make_section(capacity=2)
    students = [
        make_student(name=f"S{i}", parents=[{"name": "P", "email": f"p{i}@e.com", "phone": "+91 90000 00000"}])
        for i in range(6)
    ]
    session_factory = client.app.state.session_factory
    barrier = threading.Barrier(len(students))

    def enroll(student):
        barrier.wait()
        with session_factory() as session:
            service = StudentService(StudentRepository(session, "2026-27"))
            try:
                service.enroll(uuid.UUID(student["id"]), EnrollmentCreate(section_id=uuid.UUID(section["id"])))
                return "enrolled"
            except ConflictError:
                return "full"

    with ThreadPoolExecutor(len(students)) as pool:
        outcomes = list(pool.map(enroll, students))

    assert outcomes.count("enrolled") == 2 and outcomes.count("full") == 4
    assert client.get("/api/v1/students", params={"section_id": section["id"]}, headers=admin).json()["total"] == 2
