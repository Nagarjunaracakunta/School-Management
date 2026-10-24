import json

import jwt
import pytest
from pydantic import ValidationError

from app.config.settings import Settings
from app.services.passwords import PasswordHasher, password_problem
from app.services.tokens import TokenIssuer
from app.utils.errors import UnauthorizedError
from app.utils.security import decode_token
from tests.conftest import decode_like_other_services


@pytest.mark.parametrize(
    ("password", "email", "expected"),
    [
        ("short", "", "at least 12"),
        ("x" * 129, "", "at most 128"),
        ("password1234", "", "too easy"),
        ("aaaaaaaaaaaaaaaa", "", "too easy"),
        ("ravikumar-is-great", "ravikumar@example.com", "email name"),
        ("a long enough secret", "", None),
        ("correct horse battery staple", "ravi@example.com", None),
        ("no symbols or digits needed at all", "", None),  # length wins; no composition rules
    ],
)
def test_password_policy(password, email, expected):
    problem = password_problem(password, email)
    assert (problem is None) if expected is None else (expected in problem)


def test_hashes_verify_and_are_salted(settings):
    hasher = PasswordHasher(settings)
    a, b = hasher.hash("a long enough secret"), hasher.hash("a long enough secret")
    assert a != b and a.startswith("$argon2id$")  # same password, different salt each time
    assert hasher.verify(a, "a long enough secret") and not hasher.verify(a, "wrong")
    assert not hasher.verify("not-a-hash", "anything")  # garbage in the database never crashes a login


def test_old_cheaper_hashes_are_flagged_for_upgrade(settings):
    stronger = settings.model_copy(update={"argon2_time_cost": 3})
    old = PasswordHasher(settings).hash("a long enough secret")
    assert PasswordHasher(stronger).needs_rehash(old)
    assert not PasswordHasher(settings).needs_rehash(old)


def test_tokens_carry_the_claims_other_services_rely_on(settings):
    from app.models.user import User

    issuer = TokenIssuer(settings)
    user = User(id=__import__("uuid").uuid4(), email="ravi@example.com", full_name="Ravi Rao", role="parent")
    token = issuer.issue(user)
    claims = decode_like_other_services(token, settings)

    assert (claims["sub"], claims["role"], claims["email"], claims["name"]) == (
        str(user.id),
        "parent",
        "ravi@example.com",
        "Ravi Rao",
    )
    assert claims["exp"] - claims["iat"] == settings.access_token_ttl_minutes * 60
    assert jwt.get_unverified_header(token) == {"alg": "RS256", "typ": "JWT", "kid": issuer.key_id}
    assert claims["jti"] != decode_like_other_services(issuer.issue(user), settings)["jti"]  # unique per token
    assert decode_token(token, settings).email == "ravi@example.com"


def test_a_tampered_or_foreign_token_is_rejected(settings):
    from cryptography.hazmat.primitives.asymmetric import rsa

    from app.models.user import User

    token = TokenIssuer(settings).issue(
        User(id=__import__("uuid").uuid4(), email="a@b.com", full_name="A", role="admin")
    )
    header, payload, signature = token.split(".")
    with pytest.raises(UnauthorizedError):
        decode_token(f"{header}.{payload[:-2]}xx.{signature}", settings)  # payload altered
    forged = jwt.encode(
        {"sub": "x", "role": "admin", "iss": "school-auth", "aud": "school-api", "exp": 9999999999},
        rsa.generate_private_key(public_exponent=65537, key_size=2048),
        algorithm="RS256",
    )
    with pytest.raises(UnauthorizedError):
        decode_token(forged, settings)  # signed by someone else


def test_jwks_publishes_a_key_that_verifies_our_tokens(settings):
    from app.models.user import User

    issuer = TokenIssuer(settings)
    jwks = issuer.jwks()
    (key,) = jwks["keys"]
    assert key["kty"] == "RSA" and key["alg"] == "RS256" and key["use"] == "sig" and key["kid"] == issuer.key_id
    assert "d" not in key and "p" not in key  # no private material, ever
    public = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key))
    token = issuer.issue(User(id=__import__("uuid").uuid4(), email="a@b.com", full_name="A", role="admin"))
    assert jwt.decode(token, public, algorithms=["RS256"], audience=settings.jwt_audience)["role"] == "admin"


def test_settings_reject_missing_or_broken_keys(private_key_pem):
    with pytest.raises(ValidationError, match="JWT_PRIVATE_KEY"):
        Settings(_env_file=None, database_url="sqlite://")
    with pytest.raises(ValidationError, match="valid unencrypted PEM"):
        Settings(_env_file=None, database_url="sqlite://", jwt_private_key="not a key")
    with pytest.raises(ValidationError, match="DATABASE_URL"):
        Settings(_env_file=None, jwt_private_key=private_key_pem)
    ok = Settings(_env_file=None, database_url="sqlite://", jwt_private_key=private_key_pem.replace("\n", "\\n"))
    assert "BEGIN PUBLIC KEY" in ok.jwt_public_key  # derived, and escaped newlines from env vars are fine
