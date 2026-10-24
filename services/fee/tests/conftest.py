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
CLASS_ID = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


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
    """Stands in for the Student Service, applying the same visibility rule: admin sees all,
    a parent sees only the children they own."""

    def __init__(self) -> None:
        self.students: dict[str, dict] = {}
        self.owners: dict[str, str] = {}
        self.classes: dict[str, str] = {}
        self.down = False

    def add_student(self, name="Asha Rao", owner="parent-1", status="ACTIVE") -> dict:
        student = {
            "id": str(uuid.uuid4()),
            "name": name,
            "status": status,
            "parents": [{"name": "Ravi Rao", "email": "ravi@example.com", "phone": "+91 98765 43210"}],
        }
        self.students[student["id"]] = student
        self.owners[student["id"]] = owner
        return student

    def _caller(self, token: str) -> dict:
        from app.utils.errors import UpstreamError

        if self.down:
            raise UpstreamError("The student service is unavailable. Please try again shortly.")
        return jwt.decode(token, options={"verify_signature": False})

    def _can_see(self, caller: dict, student_id: str) -> bool:
        return caller["role"] == "admin" or self.owners.get(student_id) == caller["sub"]

    def get_student(self, student_id: str, token: str) -> dict:
        from app.utils.errors import NotFoundError

        caller = self._caller(token)
        if student_id not in self.students or not self._can_see(caller, student_id):
            raise NotFoundError("Student not found")
        return self.students[student_id]

    def list_student_ids(self, token: str) -> list[str]:
        caller = self._caller(token)
        return [i for i in self.students if self._can_see(caller, i)]

    def list_classes(self, token: str) -> dict[str, str]:
        self._caller(token)
        return self.classes


@pytest.fixture
def students() -> FakeStudents:
    fake = FakeStudents()
    fake.classes[str(CLASS_ID)] = "Grade 3"
    return fake


@pytest.fixture
def client(settings, publisher, students):
    with TestClient(create_app(settings, publisher, students), raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def admin(auth):
    return auth()


@pytest.fixture
def parent1(auth):
    return auth(sub="parent-1", role="parent")


@pytest.fixture
def parent2(auth):
    return auth(sub="parent-2", role="parent")


@pytest.fixture
def make_structure(client, admin):
    def _make(name="Tuition Term 1", amount="15000.00", days_until_due=30) -> dict:
        r = client.post(
            "/api/v1/fee-structures",
            json={
                "name": name,
                "class_id": str(CLASS_ID),
                "academic_year": "2026-27",
                "amount": amount,
                "due_date": (date.today() + timedelta(days=days_until_due)).isoformat(),
            },
            headers=admin,
        )
        assert r.status_code == 201, r.text
        return r.json()

    return _make


@pytest.fixture
def make_fee(client, admin, students, make_structure):
    """Creates structure + student + fee; returns the fee JSON."""

    def _make(student=None, amount=None, **structure_kwargs) -> dict:
        student = student or students.add_student()
        structure = make_structure(**structure_kwargs)
        body = {"student_id": student["id"], "structure_id": structure["id"]}
        if amount:
            body["amount"] = amount
        r = client.post("/api/v1/fees", json=body, headers=admin)
        assert r.status_code == 201, r.text
        return r.json()

    return _make


@pytest.fixture
def pay(client):
    def _pay(headers, fee_id, amount="1000.00", method="UPI", key=None):
        return client.post(
            "/api/v1/payments",
            json={"fee_id": fee_id, "amount": amount, "method": method},
            headers={**headers, "Idempotency-Key": key or str(uuid.uuid4())},
        )

    return _pay


@pytest.fixture
def publisher() -> FakePublisher:
    return FakePublisher()


@pytest.fixture
def auth(make_token):
    def _headers(**kw) -> dict[str, str]:
        return {"Authorization": f"Bearer {make_token(**kw)}"}

    return _headers
