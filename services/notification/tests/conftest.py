import json
import os
import time
import uuid

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


@pytest.fixture(autouse=True)
def fake_aws_credentials(monkeypatch):
    """Guarantees no test can ever reach real AWS, even by accident."""
    for key, value in {
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "AWS_DEFAULT_REGION": "ap-south-1",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)


class FakeSender:
    """Records what would be sent. Can fail for everything or only for chosen recipients."""

    def __init__(self) -> None:
        self.sent: list = []
        self.fail = False
        self.fail_recipients: set[str] = set()

    def send(self, notification) -> str:
        if self.fail or notification.recipient in self.fail_recipients:
            raise RuntimeError("SNS unavailable")
        self.sent.append((notification.channel, notification.recipient, notification.subject, notification.body))
        return f"msg-{len(self.sent)}"


@pytest.fixture
def sender() -> FakeSender:
    return FakeSender()


@pytest.fixture
def client(settings, sender):
    with TestClient(create_app(settings, sender), raise_server_exceptions=False) as c:
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
def parent(auth):
    return auth(sub="parent-1", role="parent", email="Ravi@Example.com")


PARENTS = [
    {"name": "Ravi Rao", "email": "ravi@example.com", "phone": "+91 98765 43210"},
    {"name": "Sita Rao", "email": "sita@example.com", "phone": "+91 91234 56780"},
]


def make_event(event_type: str, data: dict, event_id: str | None = None) -> str:
    return json.dumps(
        {
            "event_id": event_id or str(uuid.uuid4()),
            "event_type": event_type,
            "version": 1,
            "occurred_at": "2026-10-24T08:00:00+00:00",
            "source": "test",
            "data": data,
        }
    )


EVENTS = {
    "admission.submitted": {"applicant_name": "Asha Rao", "class_applied": "Grade 3", "parents": PARENTS},
    "admission.approved": {"applicant_name": "Asha Rao", "class_applied": "Grade 3", "parents": PARENTS},
    "admission.rejected": {"applicant_name": "Asha Rao", "class_applied": "Grade 3", "parents": PARENTS},
    "payment.completed": {
        "receipt_no": "RCT-20261024-AB12CD34",
        "fee_name": "Tuition Term 1",
        "student_name": "Asha Rao",
        "amount": "6000.00",
        "balance_after": "9000.00",
        "parents": PARENTS,
    },
    "fee.overdue": {
        "student_name": "Asha Rao",
        "fee_name": "Tuition Term 1",
        "amount_outstanding": "9000.00",
        "due_date": "2026-10-01",
        "days_overdue": 23,
        "parents": PARENTS,
    },
    "attendance.absent": {
        "student_name": "Asha Rao",
        "class_name": "Grade 3",
        "section_name": "A",
        "date": "2026-10-24",
        "parents": PARENTS,
    },
}


@pytest.fixture
def event():
    """event('payment.completed') -> JSON body with realistic data; override fields via kwargs."""

    def _event(event_type: str, event_id: str | None = None, **overrides) -> str:
        return make_event(event_type, {**EVENTS[event_type], **overrides}, event_id)

    return _event


@pytest.fixture
def processor(client):
    from app.services.event_processor import EventProcessor

    return EventProcessor(client.app.state.session_factory, client.app.state.deliverer)
