import os
import time
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


class FakeStudentClient:
    """Stands in for the Student Service; records calls and can simulate an outage."""

    def __init__(self) -> None:
        self.calls: list[tuple[dict, str]] = []
        self.down = False

    def create_student(self, payload: dict, token: str) -> dict:
        from app.utils.errors import UpstreamError

        if self.down:
            raise UpstreamError("The student service is unavailable. Please try again shortly.")
        self.calls.append((payload, token))
        return {"id": "22222222-2222-2222-2222-222222222222"}


@pytest.fixture
def students() -> FakeStudentClient:
    return FakeStudentClient()


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
def valid_payload() -> dict:
    return {
        "applicant_name": "Asha Rao",
        "date_of_birth": (date.today() - timedelta(days=365 * 8)).isoformat(),
        "class_applied": "Grade 3",
        "parents": [{"name": "Ravi Rao", "email": "ravi@example.com", "phone": "+91 98765 43210"}],
    }
