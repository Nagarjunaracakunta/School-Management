"""Runs the bootstrap against a real PostgreSQL whose administrator is NOT a superuser (like RDS).
Needs TEST_PG_SUPERUSER_DSN, otherwise skipped."""

import psycopg
import pytest

import bootstrap
from bootstrap import BootstrapError
from tests.conftest import needs_postgres

pytestmark = needs_postgres


def as_role(w, service, kind):
    user = f"{service}_{'svc' if kind == 'app' else 'migrator'}"
    return w.connect(user, w.passwords[f"{service}_{kind}"])


def denied(conn, statement) -> bool:
    try:
        conn.execute(statement)
    except psycopg.errors.InsufficientPrivilege:
        return True
    except psycopg.errors.UndefinedTable:
        return False
    return False


def test_it_creates_a_schema_and_two_roles_per_service(pg_world):
    bootstrap.run(pg_world.environ())
    with pg_world.connect(pg_world.master_user, pg_world.master_password) as admin:
        schemas = {r[0] for r in admin.execute("SELECT nspname FROM pg_namespace").fetchall()}
        roles = {r[0] for r in admin.execute("SELECT rolname FROM pg_roles WHERE rolname ~ '_(svc|migrator)$'").fetchall()}
    assert {"admission", "student", "fee"} <= schemas
    assert roles == {f"{s}_{k}" for s in ("admission", "student", "fee") for k in ("svc", "migrator")}


def test_the_roles_find_their_own_schema_without_naming_it(pg_world):
    bootstrap.run(pg_world.environ())
    with as_role(pg_world, "fee", "migrator") as conn:
        assert conn.execute("SHOW search_path").fetchone()[0] == "fee"
        conn.execute("CREATE TABLE payments (id int PRIMARY KEY, amount numeric)")
        assert conn.execute("SELECT schemaname FROM pg_tables WHERE tablename = 'payments'").fetchone()[0] == "fee"


def test_the_running_service_can_read_and_write_rows_but_nothing_more(pg_world):
    bootstrap.run(pg_world.environ())
    with as_role(pg_world, "fee", "migrator") as migrator:
        migrator.execute("CREATE TABLE payments (id int PRIMARY KEY, amount numeric)")  # created AFTER the bootstrap
    with as_role(pg_world, "fee", "app") as app:
        app.execute("INSERT INTO payments VALUES (1, 100)")  # the table did not exist when privileges were granted
        app.execute("UPDATE payments SET amount = 150 WHERE id = 1")
        assert app.execute("SELECT amount FROM payments").fetchone()[0] == 150
        assert denied(app, "DELETE FROM payments")
        assert denied(app, "DROP TABLE payments")
        assert denied(app, "TRUNCATE payments")
        assert denied(app, "CREATE TABLE evil (x int)")
        assert denied(app, "ALTER TABLE payments ADD COLUMN y int")


def test_a_service_cannot_see_another_services_data(pg_world):
    bootstrap.run(pg_world.environ())
    with as_role(pg_world, "student", "migrator") as m:
        m.execute("CREATE TABLE students (id int)")
    with as_role(pg_world, "fee", "app") as fee, as_role(pg_world, "fee", "migrator") as fee_m:
        assert denied(fee, "SELECT * FROM student.students")
        assert denied(fee_m, "SELECT * FROM student.students")
        assert denied(fee_m, "CREATE TABLE student.sneaky (x int)")


def test_the_migrator_cannot_drop_or_take_over_the_schema(pg_world):
    bootstrap.run(pg_world.environ())
    with as_role(pg_world, "fee", "migrator") as m:
        assert denied(m, "DROP SCHEMA fee CASCADE")
        assert denied(m, "ALTER SCHEMA fee OWNER TO fee_migrator")


def test_nobody_else_can_connect_to_the_database_at_all(pg_world):
    bootstrap.run(pg_world.environ())
    with pg_world.connect(pg_world.master_user, pg_world.master_password) as admin:
        admin.execute("CREATE ROLE stranger LOGIN PASSWORD 'stranger-password-123'")
    try:
        with pytest.raises(psycopg.OperationalError):
            pg_world.connect("stranger", "stranger-password-123")
    finally:
        with pg_world.connect(pg_world.master_user, pg_world.master_password) as admin:
            admin.execute("DROP ROLE stranger")


def test_running_it_again_changes_nothing_and_fixes_missing_grants(pg_world):
    bootstrap.run(pg_world.environ())
    with as_role(pg_world, "student", "migrator") as m:
        m.execute("CREATE TABLE students (id int)")
        m.execute("REVOKE ALL ON students FROM student_svc")  # simulate drift
    bootstrap.run(pg_world.environ())  # again
    with as_role(pg_world, "student", "app") as app:
        app.execute("INSERT INTO students VALUES (1)")  # the grant is back


def test_rotating_a_password_in_secrets_manager_reaches_the_database(pg_world):
    bootstrap.run(pg_world.environ())
    old = pg_world.passwords["fee_app"]
    pg_world.sm.put_secret_value(
        SecretId=pg_world.app_arns["fee"],
        SecretString=__import__("json").dumps(
            {
                "username": "fee_svc",
                "password": "brand-new-password-0123456789",
                "host": pg_world.host,
                "port": pg_world.port,
                "dbname": pg_world.dbname,
            }
        ),
    )
    bootstrap.run(pg_world.environ())
    with pytest.raises(psycopg.OperationalError):
        pg_world.connect("fee_svc", old)  # the old password is dead
    pg_world.connect("fee_svc", "brand-new-password-0123456789").close()


def test_passwords_with_quotes_and_backslashes_survive(pg_world):
    pw = "it's-a-\\tricky\"password-0123456789"
    pg_world.app_arns["fee"] = pg_world.login_secret("fee", "app", pw=pw)
    bootstrap.run(pg_world.environ())
    pg_world.connect("fee_svc", pw).close()


def test_the_administrator_is_untouched(pg_world):
    bootstrap.run(pg_world.environ())
    pg_world.connect(pg_world.master_user, pg_world.master_password).close()  # same password as before


def test_a_refused_secret_leaves_the_database_exactly_as_it_was(pg_world):
    pg_world.app_arns["fee"] = pg_world.login_secret("fee", "app", username=pg_world.master_user)  # tries to hijack the admin
    with pytest.raises(BootstrapError):
        bootstrap.run(pg_world.environ())
    with pg_world.connect(pg_world.master_user, pg_world.master_password) as admin:
        assert admin.execute("SELECT count(*) FROM pg_roles WHERE rolname ~ '_(svc|migrator)$'").fetchone()[0] == 0
        assert (
            admin.execute("SELECT count(*) FROM pg_namespace WHERE nspname IN ('fee','student','admission')").fetchone()[0] == 0
        )


def test_a_wrong_administrator_password_fails_without_leaking_it(pg_world, monkeypatch):
    monkeypatch.setattr(bootstrap, "CONNECT_ATTEMPTS", 1)
    pg_world.sm.put_secret_value(
        SecretId=pg_world.master_arn,
        SecretString=__import__("json").dumps({"username": pg_world.master_user, "password": "definitely-the-wrong-password"}),
    )
    with pytest.raises(BootstrapError) as err:
        bootstrap.run(pg_world.environ())
    assert "definitely-the-wrong-password" not in str(err.value)


def test_the_whole_run_is_one_transaction(pg_world, monkeypatch):
    """If something fails halfway, no half-built roles are left behind."""
    original = bootstrap._ident
    calls = {"n": 0}

    def flaky(name):
        calls["n"] += 1
        if name == "student":  # fail while building the SECOND service
            raise BootstrapError("boom")
        return original(name)

    monkeypatch.setattr(bootstrap, "_ident", flaky)
    with pytest.raises(BootstrapError):
        bootstrap.run(pg_world.environ())
    with pg_world.connect(pg_world.master_user, pg_world.master_password) as admin:
        assert admin.execute("SELECT count(*) FROM pg_roles WHERE rolname ~ '_(svc|migrator)$'").fetchone()[0] == 0
