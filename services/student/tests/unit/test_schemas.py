from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from app.schemas.academic import SubjectCreate
from app.schemas.student import EnrollmentCreate, StudentCreate


def test_valid_student(student_payload):
    assert StudentCreate(**student_payload).name == "Asha Rao"


def test_student_needs_a_parent(student_payload):
    student_payload["parents"] = []
    with pytest.raises(ValidationError):
        StudentCreate(**student_payload)


def test_implausible_birth_date(student_payload):
    student_payload["date_of_birth"] = (date.today() - timedelta(days=30)).isoformat()
    with pytest.raises(ValidationError):
        StudentCreate(**student_payload)


@pytest.mark.parametrize("year", ["2026", "26-27", "2026/27", "abcd-ef"])
def test_bad_academic_year(year):
    with pytest.raises(ValidationError):
        EnrollmentCreate(section_id="00000000-0000-0000-0000-000000000000", academic_year=year)


def test_subject_code_is_upper_cased():
    assert SubjectCreate(name="Maths", code="math1").code == "MATH1"
