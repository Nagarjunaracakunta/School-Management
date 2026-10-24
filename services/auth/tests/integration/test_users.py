import uuid

import pytest

from app.cli import create_admin, main
from app.services.passwords import PasswordHasher
from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD

USERS = "/api/v1/users"
NEW = {"email": "Teacher@School.org", "full_name": "Mr Teacher", "role": "teacher", "password": "a long enough secret"}


def test_admin_creates_a_user_and_the_hash_never_leaks(client, admin_headers):
    r = client.post(USERS, json=NEW, headers=admin_headers)
    assert r.status_code == 201
    body = r.json()
    assert body["email"] == "teacher@school.org" and body["role"] == "teacher" and body["is_active"] is True
    assert r.headers["Location"] == f"{USERS}/{body['id']}"
    assert "password" not in str(body).lower() and "argon2" not in str(body)


def test_only_admins_manage_users(client, make_user, admin_headers):
    _, parent = make_user(role="parent", email="p@example.com")
    _, teacher = make_user(role="teacher", email="t@example.com")
    for headers in (parent, teacher):
        assert client.post(USERS, json=NEW, headers=headers).status_code == 403
        assert client.get(USERS, headers=headers).status_code == 403
        assert client.put(f"{USERS}/{uuid.uuid4()}", json={"is_active": False}, headers=headers).status_code == 403
        assert (
            client.post(
                f"{USERS}/{uuid.uuid4()}/password", json={"new_password": "x" * 14}, headers=headers
            ).status_code
            == 403
        )
    assert client.post(USERS, json=NEW).status_code == 401
    assert client.get(USERS, headers={"Authorization": "Bearer not.a.token"}).status_code == 401


def test_duplicate_emails_conflict_regardless_of_case(client, admin_headers):
    assert client.post(USERS, json=NEW, headers=admin_headers).status_code == 201
    again = client.post(USERS, json={**NEW, "email": "TEACHER@school.ORG"}, headers=admin_headers)
    assert again.status_code == 409 and again.json()["error"]["code"] == "conflict"


@pytest.mark.parametrize(
    ("password", "fragment"),
    [("short", "at least 12"), ("password1234", "too easy"), ("teacher-for-ever", "email name")],
)
def test_weak_passwords_are_refused_with_a_reason(client, admin_headers, password, fragment):
    r = client.post(USERS, json={**NEW, "password": password}, headers=admin_headers)
    assert r.status_code == 422 and fragment in str(r.json()["error"]["details"])


def test_invalid_role_and_email_are_422(client, admin_headers):
    assert client.post(USERS, json={**NEW, "role": "superuser"}, headers=admin_headers).status_code == 422
    assert client.post(USERS, json={**NEW, "email": "nope"}, headers=admin_headers).status_code == 422


def test_listing_filters_and_pagination(client, make_user, admin_headers):
    make_user("parent", "a@example.com", name="Anita")
    make_user("parent", "b@example.com", name="Bhavna")
    make_user("teacher", "c@example.com", name="Chetan")

    def total(**params):
        return client.get(USERS, params=params, headers=admin_headers).json()["total"]

    assert total() == 4 and total(role="parent") == 2 and total(role="admin") == 1
    assert total(q="bhav") == 1 and total(q="c@example") == 1 and total(q="%") == 0
    assert total(is_active="false") == 0
    page = client.get(USERS, params={"page": 2, "page_size": 3}, headers=admin_headers).json()
    assert (page["total"], len(page["items"])) == (4, 1)
    assert client.get(USERS, params={"role": "wizard"}, headers=admin_headers).status_code == 422


def test_reading_a_user_is_admin_or_self(client, make_user, admin_headers):
    mine, my_headers = make_user(email="me@example.com")
    other, _ = make_user(email="other@example.com", name="Other")
    assert client.get(f"{USERS}/{mine['id']}", headers=my_headers).status_code == 200
    assert client.get(f"{USERS}/{other['id']}", headers=my_headers).status_code == 404  # looks like it does not exist
    assert client.get(f"{USERS}/{other['id']}", headers=admin_headers).status_code == 200
    assert client.get(f"{USERS}/{uuid.uuid4()}", headers=admin_headers).status_code == 404
    assert client.get(f"{USERS}/not-a-uuid", headers=admin_headers).status_code == 422


def test_updating_role_name_and_status(client, make_user, admin_headers, login):
    user, _ = make_user(email="u@example.com")
    r = client.put(f"{USERS}/{user['id']}", json={"role": "teacher", "full_name": "New Name"}, headers=admin_headers)
    assert r.status_code == 200 and (r.json()["role"], r.json()["full_name"]) == ("teacher", "New Name")
    client.put(f"{USERS}/{user['id']}", json={"is_active": False}, headers=admin_headers)
    assert login("u@example.com", "a long enough secret").status_code == 401  # disabled: cannot log in
    client.put(f"{USERS}/{user['id']}", json={"is_active": True}, headers=admin_headers)
    assert login("u@example.com", "a long enough secret").status_code == 200
    assert client.put(f"{USERS}/{user['id']}", json={}, headers=admin_headers).status_code == 422
    assert client.put(f"{USERS}/{uuid.uuid4()}", json={"is_active": False}, headers=admin_headers).status_code == 404


def test_the_school_can_never_be_locked_out_of_administration(client, make_admin, admin_headers, login):
    me = client.get("/api/v1/auth/me", headers=admin_headers).json()
    assert client.put(f"{USERS}/{me['id']}", json={"role": "teacher"}, headers=admin_headers).status_code == 409
    assert client.put(f"{USERS}/{me['id']}", json={"is_active": False}, headers=admin_headers).status_code == 409

    second_id = make_admin("second.admin@school.org", "another long secret", "Second")
    second = {
        "Authorization": f"Bearer {login('second.admin@school.org', 'another long secret').json()['access_token']}"
    }
    # With two admins one may demote the other...
    assert client.put(f"{USERS}/{second_id}", json={"role": "teacher"}, headers=admin_headers).status_code == 200
    # ...but the last remaining admin can never be removed, not even by another admin
    last = client.put(f"{USERS}/{me['id']}", json={"is_active": False}, headers=second)
    assert last.status_code == 409  # `second` is now a teacher, so it is refused before anything else
    assert client.get(USERS, params={"role": "admin"}, headers=admin_headers).json()["total"] == 1


def test_admin_reset_sets_a_new_password_and_unlocks(client, make_user, admin_headers, login):
    user, _ = make_user(email="forgot@example.com")
    for _ in range(5):
        login("forgot@example.com", "wrong password")
    assert login("forgot@example.com", "a long enough secret").status_code == 401  # locked

    r = client.post(
        f"{USERS}/{user['id']}/password", json={"new_password": "a brand new secret"}, headers=admin_headers
    )
    assert r.status_code == 204
    assert login("forgot@example.com", "a long enough secret").status_code == 401  # old password is dead
    assert login("forgot@example.com", "a brand new secret").status_code == 200  # and the lock is gone
    weak = client.post(f"{USERS}/{user['id']}/password", json={"new_password": "short"}, headers=admin_headers)
    assert weak.status_code == 422
    assert (
        client.post(
            f"{USERS}/{uuid.uuid4()}/password", json={"new_password": "a brand new secret"}, headers=admin_headers
        ).status_code
        == 404
    )


def test_users_change_their_own_password(client, make_user, login):
    _, headers = make_user(email="self@example.com")
    path = "/api/v1/auth/change-password"
    wrong = client.post(
        path, json={"current_password": "not mine", "new_password": "a second long secret"}, headers=headers
    )
    assert (
        wrong.status_code == 422 and "incorrect" in wrong.json()["error"]["message"]
    )  # 422 so the UI does not log out
    weak = client.post(
        path, json={"current_password": "a long enough secret", "new_password": "short"}, headers=headers
    )
    assert weak.status_code == 422
    ok = client.post(
        path, json={"current_password": "a long enough secret", "new_password": "a second long secret"}, headers=headers
    )
    assert ok.status_code == 204
    assert login("self@example.com", "a long enough secret").status_code == 401
    assert login("self@example.com", "a second long secret").status_code == 200
    assert client.post(path, json={"current_password": "x", "new_password": "a second long secret"}).status_code == 401


def test_cli_creates_the_first_admin_exactly_once(client, settings, login, monkeypatch):
    monkeypatch.setenv("AUTH_ADMIN_PASSWORD", "an admin passphrase")
    # An in-memory SQLite URL would give the CLI its own empty database, so share the app's connection
    monkeypatch.setattr("app.cli.build_session_factory", lambda engine: client.app.state.session_factory)
    main(["create-admin", "--email", "First@School.org", "--name", "First Admin"], settings=client.app.state.settings)
    assert login("first@school.org", "an admin passphrase").status_code == 200

    factory, hasher = client.app.state.session_factory, PasswordHasher(settings)
    with pytest.raises(SystemExit, match="already exists"):
        create_admin(factory, hasher, "first@school.org", "Again", "another long secret")
    with pytest.raises(SystemExit, match="at least 12"):
        create_admin(factory, hasher, "x@school.org", "Weak", "short")
    assert login("first@school.org", "an admin passphrase").status_code == 200  # untouched by the failed attempts


def test_the_default_admin_helper_works(make_admin, login):
    make_admin()
    assert login(ADMIN_EMAIL, ADMIN_PASSWORD).status_code == 200
