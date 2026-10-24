"""Needs PostgreSQL: skipped on the default in-memory SQLite."""

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL", "").startswith("postgresql"), reason="needs PostgreSQL"
)


def test_two_people_marking_the_same_student_at_once_never_fail(client, students, admin, teacher1):
    asha = students.add_student()
    students.add_teacher()
    barrier = threading.Barrier(6)
    statuses = ["PRESENT", "ABSENT", "LATE", "ABSENT", "PRESENT", "LATE"]
    payload = {"subject_type": "student", "subject_id": asha["id"], "date": date.today().isoformat()}

    def mark(status):
        barrier.wait()
        return client.post("/api/v1/attendance", json={**payload, "status": status}, headers=admin).status_code

    with ThreadPoolExecutor(6) as pool:
        codes = list(pool.map(mark, statuses))

    assert set(codes) <= {200, 201} and codes.count(201) == 1  # one creation, the rest are corrections
    history = client.get(f"/api/v1/students/{asha['id']}/attendance", headers=admin).json()
    assert history["total"] == 1  # a single record for the day, whoever won
