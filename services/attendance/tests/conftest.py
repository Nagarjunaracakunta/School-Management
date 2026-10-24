import os
import time
import uuid
from datetime import date, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.config.settings import Settings
from app.main import create_app
from app.models.base import Base

ISSUER, AUDIENCE = "school-auth", "school-api"
SEC_3A = "3a3a3a3a-0000-4000-8000-000000000001"
SEC_4B = "4b4b4b4b-0000-4000-8000-000000000002"


@pytest.fixture(scope="session")
def keypair() -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    public = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    return private, public


@pytest.fixture
def make_token(keypair):
    def _make(sub="admin-1", role="admin", name="Test User", expires_in=600, **overrides) -> str:
        claims = {
            "sub": sub,
            "role": role,
            "name": name,
            "iss": ISSUER,
            "aud": AUDIENCE,
            "exp": int(time.time()) + expires_in,
        }
        claims.update(overrides)
        return jwt.encode(claims, keypair[0], algorithm="RS256")

    return _make


@pytest.fixture(autouse=True)
def fresh_database():
    """With TEST_DATABASE_URL set (a PostgreSQL URL) every test starts from empty tables. The default is
    an in-memory SQLite database, which is thrown away by itself."""
    url = os.getenv("TEST_DATABASE_URL")
    if url:
        from sqlalchemy import create_engine

        engine = create_engine(url)
        Base.metadata.drop_all(engine)
        engine.dispose()
    yield


@pytest.fixture
def settings(keypair) -> Settings:
    return Settings(
        database_url=os.getenv("TEST_DATABASE_URL", "sqlite://"),
        auto_create_tables=True,
        outbox_enabled=False,  # tests drive the relay by hand
        jwt_public_key=keypair[1],
        jwt_issuer=ISSUER,
        jwt_audience=AUDIENCE,
    )


class FakePublisher:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []
        self.fail = False

    def publish(self, event_type: str, body: str) -> None:
        if self.fail:
            raise RuntimeError("SQS unavailable")
        self.sent.append((event_type, body))


class FakeStudents:
    """Stands in for the Student Service with the same visibility rules: admin sees everyone, a parent
    sees only their own children, a teacher sees only students in sections they teach."""

    def __init__(self) -> None:
        self.students: dict[str, dict] = {}
        self.owners: dict[str, str] = {}
        self.teachers: dict[str, dict] = {}
        self.teaching: dict[str, set[str]] = {}  # teacher login -> section ids they teach
        self.down = False

    def add_student(
        self, name="Asha Rao", owner="parent-1", section=SEC_3A, class_name="Grade 3", section_name="A", status="ACTIVE"
    ) -> dict:
        student = {
            "id": str(uuid.uuid4()),
            "name": name,
            "status": status,
            "class_name": class_name,
            "section_name": section_name,
            "section_id": section,
            "parents": [{"name": "Ravi Rao", "email": "ravi@example.com", "phone": "+91 98765 43210"}],
        }
        self.students[student["id"]] = student
        self.owners[student["id"]] = owner
        return student

    def add_teacher(self, name="Mr T", login="teacher-1", sections=(SEC_3A,)) -> dict:
        teacher = {"id": str(uuid.uuid4()), "name": name, "email": f"{login}@school.org", "user_id": login}
        self.teachers[teacher["id"]] = teacher
        self.teaching[login] = set(sections)
        return teacher

    def _caller(self, token: str) -> dict:
        from app.utils.errors import UpstreamError

        if self.down:
            raise UpstreamError("The student service is unavailable. Please try again shortly.")
        return jwt.decode(token, options={"verify_signature": False})

    def _can_see(self, caller: dict, student: dict) -> bool:
        if caller["role"] == "admin":
            return True
        if caller["role"] == "parent":
            return self.owners[student["id"]] == caller["sub"]
        return student["section_id"] in self.teaching.get(caller["sub"], set())

    def get_student(self, student_id: str, token: str) -> dict:
        from app.utils.errors import NotFoundError

        caller = self._caller(token)
        student = self.students.get(student_id)
        if student is None or not self._can_see(caller, student):
            raise NotFoundError("Student not found")
        return student

    def list_student_ids(self, token: str) -> list[str]:
        caller = self._caller(token)
        return [i for i, s in self.students.items() if self._can_see(caller, s)]

    def list_section_students(self, section_id: str, token: str) -> list[dict]:
        caller = self._caller(token)
        return [
            s
            for s in self.students.values()
            if s["section_id"] == section_id and s["status"] == "ACTIVE" and self._can_see(caller, s)
        ]

    def list_teachers(self, token: str) -> list[dict]:
        self._caller(token)
        return list(self.teachers.values())


@pytest.fixture
def students() -> FakeStudents:
    return FakeStudents()


@pytest.fixture
def publisher() -> FakePublisher:
    return FakePublisher()


@pytest.fixture
def client(settings, publisher, students):
    with TestClient(create_app(settings, publisher, students), raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def auth(make_token):
    def _headers(**kw) -> dict[str, str]:
        return {"Authorization": f"Bearer {make_token(**kw)}"}

    return _headers


@pytest.fixture
def admin(auth):
    return auth()


@pytest.fixture
def teacher1(auth):
    return auth(sub="teacher-1", role="teacher")


@pytest.fixture
def parent1(auth):
    return auth(sub="parent-1", role="parent")


@pytest.fixture
def mark(client):
    """mark(headers, student, status='PRESENT', days_ago=0) -> response"""

    def _mark(headers, student, status="PRESENT", days_ago=0, subject_type="student"):
        subject_id = student["id"] if isinstance(student, dict) else student
        return client.post(
            "/api/v1/attendance",
            json={
                "subject_type": subject_type,
                "subject_id": subject_id,
                "date": (date.today() - timedelta(days=days_ago)).isoformat(),
                "status": status,
            },
            headers=headers,
        )

    return _mark
