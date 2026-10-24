import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.utils.errors import UnauthorizedError
from app.utils.request_context import resolve_request_id
from app.utils.security import Role, decode_token


def test_valid_token(settings, make_token):
    user = decode_token(make_token(sub="u1", role="parent"), settings)
    assert (user.id, user.role) == ("u1", Role.PARENT)


@pytest.mark.parametrize(
    "overrides",
    [{"expires_in": -10}, {"aud": "someone-else"}, {"iss": "evil"}, {"role": "superuser"}],
)
def test_bad_claims_rejected(settings, make_token, overrides):
    with pytest.raises(UnauthorizedError):
        decode_token(make_token(**overrides), settings)


def test_token_signed_with_other_key_rejected(settings):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = jwt.encode(
        {"sub": "x", "role": "admin", "iss": "school-auth", "aud": "school-api", "exp": 9999999999},
        other,
        algorithm="RS256",
    )
    with pytest.raises(UnauthorizedError):
        decode_token(token, settings)


def test_unsigned_alg_none_rejected(settings):
    token = jwt.encode({"sub": "x", "role": "admin"}, key=None, algorithm="none")
    with pytest.raises(UnauthorizedError):
        decode_token(token, settings)


def test_request_id_rules():
    assert resolve_request_id("abc12345-good") == "abc12345-good"
    assert resolve_request_id("bad\nid") != "bad\nid"
    assert resolve_request_id(None)
