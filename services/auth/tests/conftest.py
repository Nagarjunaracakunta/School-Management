import os

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.config.settings import Settings
from app.main import create_app
from app.models.base import Base

ADMIN_EMAIL, ADMIN_PASSWORD = "head.admin@school.org", "correct horse battery"


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


@pytest.fixture(scope="session")
def private_key_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()


@pytest.fixture
def settings(private_key_pem) -> Settings:
    return Settings(
        _env_file=None,
        database_url=os.getenv("TEST_DATABASE_URL", "sqlite://"),
        auto_create_tables=True,
        jwt_private_key=private_key_pem,
        max_failed_logins=5,
        lockout_minutes=15,
        # Cheap hashing keeps the suite fast; production uses the strong defaults
        argon2_time_cost=2,
        argon2_memory_kib=8,
        argon2_parallelism=1,
    )


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings), raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def make_admin(client):
    """Creates an administrator the same way production does: through the operator CLI."""

    def _make(email=ADMIN_EMAIL, password=ADMIN_PASSWORD, name="Head Admin") -> str:
        from app.cli import create_admin
        from app.services.passwords import PasswordHasher

        return create_admin(
            client.app.state.session_factory, PasswordHasher(client.app.state.settings), email, name, password
        )

    return _make


@pytest.fixture
def login(client):
    def _login(email, password):
        return client.post("/api/v1/auth/login", json={"email": email, "password": password})

    return _login


@pytest.fixture
def admin_headers(make_admin, login):
    make_admin()
    token = login(ADMIN_EMAIL, ADMIN_PASSWORD).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def make_user(client, admin_headers, login):
    """Creates a user through the API and returns (user_json, auth_headers_for_that_user)."""

    def _make(role="parent", email="ravi@example.com", password="a long enough secret", name="Ravi Rao"):
        r = client.post(
            "/api/v1/users",
            json={"email": email, "full_name": name, "role": role, "password": password},
            headers=admin_headers,
        )
        assert r.status_code == 201, r.text
        token = login(email, password).json()["access_token"]
        return r.json(), {"Authorization": f"Bearer {token}"}

    return _make


def decode_like_other_services(token: str, settings: Settings) -> dict:
    """Exactly what the other five services do to verify a token."""
    return jwt.decode(
        token,
        settings.jwt_public_key,
        algorithms=["RS256"],
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        options={"require": ["exp", "sub", "iss", "aud"]},
    )
