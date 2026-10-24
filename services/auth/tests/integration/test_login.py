import datetime as dt

import pytest

from app.models.user import User
from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD, decode_like_other_services

LOGIN = "/api/v1/auth/login"


def user_row(client, email):
    with client.app.state.session_factory() as session:
        return session.query(User).filter(User.email == email).one()


def test_successful_login_returns_a_verifiable_token(client, settings, make_admin, login):
    user_id = make_admin()
    r = login(ADMIN_EMAIL, ADMIN_PASSWORD)
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer" and body["expires_in"] == 30 * 60
    assert r.headers["Cache-Control"] == "no-store"
    claims = decode_like_other_services(body["access_token"], settings)
    assert (claims["sub"], claims["role"], claims["email"]) == (user_id, "admin", ADMIN_EMAIL)
    assert user_row(client, ADMIN_EMAIL).last_login_at is not None


def test_email_is_case_and_whitespace_insensitive(make_admin, login):
    make_admin()
    assert login("  HEAD.Admin@School.ORG ", ADMIN_PASSWORD).status_code == 200


def test_every_kind_of_failure_looks_identical(client, make_admin, make_user, login, admin_headers):
    user, _ = make_user(email="gone@example.com")
    client.put(f"/api/v1/users/{user['id']}", json={"is_active": False}, headers=admin_headers)

    attempts = {
        "wrong password": login(ADMIN_EMAIL, "definitely not it"),
        "unknown email": login("nobody@example.com", ADMIN_PASSWORD),
        "disabled account, right password": login("gone@example.com", "a long enough secret"),
    }
    for response in attempts.values():
        assert response.status_code == 401
    messages = {r.json()["error"]["message"] for r in attempts.values()}
    codes = {r.json()["error"]["code"] for r in attempts.values()}
    assert messages == {"Invalid email or password"} and codes == {"unauthorized"}


def test_unknown_emails_cost_the_same_as_real_ones(client, make_admin, login, monkeypatch):
    make_admin()
    hasher = client.app.state.hasher
    calls = {"dummy": 0}
    real = hasher.verify_dummy
    monkeypatch.setattr(
        hasher, "verify_dummy", lambda pw: (calls.__setitem__("dummy", calls["dummy"] + 1), real(pw))[1]
    )
    login("nobody@example.com", "whatever password")
    assert calls["dummy"] == 1  # a hash was still computed, so response time reveals nothing


def test_repeated_failures_lock_the_account_even_for_the_right_password(client, make_admin, login):
    make_admin()
    for _ in range(5):
        assert login(ADMIN_EMAIL, "wrong password").status_code == 401
    row = user_row(client, ADMIN_EMAIL)
    assert row.locked_until is not None and row.failed_attempts == 0

    locked = login(ADMIN_EMAIL, ADMIN_PASSWORD)  # correct, but locked
    assert locked.status_code == 401 and locked.json()["error"]["message"] == "Invalid email or password"


def test_locked_accounts_do_not_check_the_real_hash(client, make_admin, login, monkeypatch):
    make_admin()
    for _ in range(5):
        login(ADMIN_EMAIL, "wrong password")
    hasher = client.app.state.hasher
    real_calls = {"n": 0}
    real = hasher.verify
    monkeypatch.setattr(
        hasher, "verify", lambda h, p: (real_calls.__setitem__("n", real_calls["n"] + 1), real(h, p))[1]
    )
    login(ADMIN_EMAIL, ADMIN_PASSWORD)
    assert real_calls["n"] == 0  # guessing during a lockout gives no signal at all


def test_lockout_expires_and_success_resets_the_counter(client, make_admin, login):
    make_admin()
    for _ in range(5):
        login(ADMIN_EMAIL, "wrong password")
    with client.app.state.session_factory() as session:  # time passes: the lock is now in the past
        row = session.query(User).filter(User.email == ADMIN_EMAIL).one()
        row.locked_until = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=1)
        session.commit()
    assert login(ADMIN_EMAIL, ADMIN_PASSWORD).status_code == 200
    row = user_row(client, ADMIN_EMAIL)
    assert (row.failed_attempts, row.locked_until) == (0, None)


def test_a_few_failures_followed_by_success_do_not_accumulate(client, make_admin, login):
    make_admin()
    for _ in range(4):
        login(ADMIN_EMAIL, "wrong password")
    assert user_row(client, ADMIN_EMAIL).failed_attempts == 4
    assert login(ADMIN_EMAIL, ADMIN_PASSWORD).status_code == 200
    assert user_row(client, ADMIN_EMAIL).failed_attempts == 0
    for _ in range(4):  # four more still do not lock: the counter really was reset
        login(ADMIN_EMAIL, "wrong password")
    assert login(ADMIN_EMAIL, ADMIN_PASSWORD).status_code == 200


def test_old_hashes_are_upgraded_at_login(client, settings, make_admin, login):
    from app.services.passwords import PasswordHasher

    make_admin()
    weaker = PasswordHasher(settings.model_copy(update={"argon2_time_cost": 1}))
    with client.app.state.session_factory() as session:
        row = session.query(User).filter(User.email == ADMIN_EMAIL).one()
        row.password_hash = weaker.hash(ADMIN_PASSWORD)
        session.commit()
    assert "t=1" in user_row(client, ADMIN_EMAIL).password_hash
    assert login(ADMIN_EMAIL, ADMIN_PASSWORD).status_code == 200
    upgraded = user_row(client, ADMIN_EMAIL).password_hash
    assert "t=2" in upgraded and login(ADMIN_EMAIL, ADMIN_PASSWORD).status_code == 200


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"email": "a@b.com"},
        {"password": "x"},
        {"email": "not-an-email", "password": "x"},
        {"email": "a@b.com", "password": ""},
    ],
)
def test_malformed_login_requests_are_422(client, body):
    r = client.post(LOGIN, json=body)
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


def test_logging_never_contains_passwords_or_full_emails(client, make_admin, login, caplog):
    make_admin()
    with caplog.at_level("INFO"):
        login(ADMIN_EMAIL, "this-secret-must-not-be-logged")
        login(ADMIN_EMAIL, ADMIN_PASSWORD)
    text = "\n".join(r.getMessage() + str(r.__dict__) for r in caplog.records)
    assert "this-secret-must-not-be-logged" not in text and ADMIN_PASSWORD not in text
    assert ADMIN_EMAIL not in text and "h***@school.org" in text


def test_deactivated_users_are_noticed_by_me_even_though_old_tokens_still_decode(client, make_user, admin_headers):
    user, headers = make_user()
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200
    client.put(f"/api/v1/users/{user['id']}", json={"is_active": False}, headers=admin_headers)
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 404


def test_jwks_and_probes(client):
    r = client.get("/.well-known/jwks.json")
    assert r.status_code == 200 and r.json()["keys"][0]["kty"] == "RSA" and "max-age" in r.headers["Cache-Control"]
    assert client.get("/health").status_code == 200 and client.get("/ready").status_code == 200
