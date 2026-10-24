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
        jwt_public_key=keypair[1],
        jwt_issuer=ISSUER,
        jwt_audience=AUDIENCE,
        current_academic_year="2026-27",
    )


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings), raise_server_exceptions=False) as c:
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
def student_payload() -> dict:
    return {
        "name": "Asha Rao",
        "date_of_birth": (date.today() - timedelta(days=365 * 8)).isoformat(),
        "parents": [{"name": "Ravi Rao", "email": "ravi@example.com", "phone": "+91 98765 43210"}],
        "guardian_user_id": "parent-1",
    }


@pytest.fixture
def make_section(client, admin):
    """Creates class + section and returns the section JSON."""

    def _make(class_name="Grade 3", section="A", capacity=40) -> dict:
        existing = client.get("/api/v1/classes", headers=admin).json()["items"]
        cls = next((c for c in existing if c["name"] == class_name), None)
        if cls is None:
            cls = client.post("/api/v1/classes", json={"name": class_name}, headers=admin).json()
        r = client.post(
            "/api/v1/sections", json={"class_id": cls["id"], "name": section, "capacity": capacity}, headers=admin
        )
        assert r.status_code == 201, r.text
        return r.json()

    return _make


@pytest.fixture
def make_student(client, admin, student_payload):
    def _make(**overrides) -> dict:
        r = client.post("/api/v1/students", json={**student_payload, **overrides}, headers=admin)
        assert r.status_code in (200, 201), r.text
        return r.json()

    return _make
