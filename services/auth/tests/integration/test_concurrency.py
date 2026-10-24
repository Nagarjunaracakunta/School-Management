"""Needs PostgreSQL (real row locks across connections): skipped on the default in-memory SQLite."""

import os
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.models.user import User
from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL", "").startswith("postgresql"), reason="needs PostgreSQL"
)


def test_simultaneous_wrong_guesses_are_all_counted(client, make_admin, login):
    """Without a lock, two parallel failures could both read '2' and both write '3' (a lost update), letting
    an attacker make more guesses than the limit allows."""
    make_admin()
    barrier = threading.Barrier(4)

    def guess(_):
        barrier.wait()
        return login(ADMIN_EMAIL, "wrong password").status_code

    with ThreadPoolExecutor(4) as pool:
        assert set(pool.map(guess, range(4))) == {401}
    with client.app.state.session_factory() as session:
        assert session.query(User).filter(User.email == ADMIN_EMAIL).one().failed_attempts == 4


def test_a_burst_of_guesses_locks_exactly_once(client, make_admin, login):
    make_admin()
    barrier = threading.Barrier(12)

    def guess(_):
        barrier.wait()
        return login(ADMIN_EMAIL, "wrong password").status_code

    with ThreadPoolExecutor(12) as pool:
        assert set(pool.map(guess, range(12))) == {401}
    assert login(ADMIN_EMAIL, ADMIN_PASSWORD).status_code == 401  # locked, even for the right password
    with client.app.state.session_factory() as session:
        assert session.query(User).filter(User.email == ADMIN_EMAIL).one().locked_until is not None


def test_two_admins_cannot_demote_each_other_at_the_same_moment(client, make_admin, login):
    """Each demotion alone is allowed (two admins exist); together they would leave zero."""
    a_id = make_admin("a.admin@school.org", "admin a long secret", "A")
    b_id = make_admin("b.admin@school.org", "admin b long secret", "B")
    token = lambda e, p: {"Authorization": f"Bearer {login(e, p).json()['access_token']}"}  # noqa: E731
    a, b = token("a.admin@school.org", "admin a long secret"), token("b.admin@school.org", "admin b long secret")
    barrier = threading.Barrier(2)

    def demote(args):
        target, headers = args
        barrier.wait()
        return client.put(f"/api/v1/users/{target}", json={"role": "teacher"}, headers=headers).status_code

    with ThreadPoolExecutor(2) as pool:
        codes = sorted(pool.map(demote, [(b_id, a), (a_id, b)]))
    with client.app.state.session_factory() as session:
        admins = session.query(User).filter(User.role == "admin", User.is_active.is_(True)).count()
    assert admins >= 1, f"nobody can administer the school any more (statuses {codes})"
