import json
import os
import secrets

import boto3
import psycopg
import pytest
from moto import mock_aws

REGION = "ap-south-1"
SERVICES = ["admission", "student", "fee"]
SUPERUSER_DSN = os.getenv("TEST_PG_SUPERUSER_DSN")  # e.g. "host=127.0.0.1 port=5433 user=postgres password=..."

needs_postgres = pytest.mark.skipif(not SUPERUSER_DSN, reason="set TEST_PG_SUPERUSER_DSN to run against a real PostgreSQL")


@pytest.fixture(autouse=True)
def fake_aws(monkeypatch):
    for k, v in {"AWS_ACCESS_KEY_ID": "testing", "AWS_SECRET_ACCESS_KEY": "testing", "AWS_DEFAULT_REGION": REGION}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)
    with mock_aws():
        yield boto3.client("secretsmanager", region_name=REGION)


def password() -> str:
    return secrets.token_hex(16)


class World:
    """A throwaway database with an RDS-like administrator, plus Secrets Manager secrets describing every login."""

    def __init__(self, sm, host: str, port: int, dbname: str, master_user: str):
        self.sm, self.host, self.port, self.dbname, self.master_user = sm, host, port, dbname, master_user
        self.master_password = password()
        self.passwords: dict[str, str] = {}
        self.app_arns: dict[str, str] = {}
        self.migrator_arns: dict[str, str] = {}
        self.master_arn = ""

    def put(self, name: str, payload: dict) -> str:
        return self.sm.create_secret(Name=name, SecretString=json.dumps(payload))["ARN"]

    def login_secret(self, service: str, kind: str, username: str | None = None, pw: str | None = None, **override) -> str:
        username = username or (f"{service}_svc" if kind == "app" else f"{service}_migrator")
        pw = pw or password()
        self.passwords[f"{service}_{kind}"] = pw
        body = {"username": username, "password": pw, "host": self.host, "port": self.port, "dbname": self.dbname, **override}
        return self.put(f"school/test/db/{service}_{kind}-{secrets.token_hex(3)}", body)

    def build(self, services=SERVICES):
        self.master_arn = self.put("rds!master", {"username": self.master_user, "password": self.master_password})
        self.app_arns = {s: self.login_secret(s, "app") for s in services}
        self.migrator_arns = {s: self.login_secret(s, "migrator") for s in services}
        return self

    def environ(self) -> dict:
        return {
            "MASTER_SECRET_ARN": self.master_arn,
            "DB_APP_SECRET_ARNS": json.dumps(self.app_arns),
            "DB_MIGRATOR_SECRET_ARNS": json.dumps(self.migrator_arns),
            "BOOTSTRAP_SSLMODE": "disable",  # the throwaway local server has no TLS; real RDS requires it (the default)
        }

    def connect(self, user: str, pw: str, **kw) -> psycopg.Connection:
        return psycopg.connect(
            host=self.host, port=self.port, dbname=self.dbname, user=user, password=pw, autocommit=True, connect_timeout=5, **kw
        )


def purge_leftovers() -> None:
    """Drops test databases (bs_*) and the roles the bootstrap creates, left behind by a crashed run."""
    with psycopg.connect(SUPERUSER_DSN + " dbname=postgres", autocommit=True) as su:
        for (name,) in su.execute("SELECT datname FROM pg_database WHERE datname LIKE 'bs\\_%'").fetchall():
            su.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        for (role,) in su.execute(
            "SELECT rolname FROM pg_roles WHERE rolname ~ '_(svc|migrator)$' OR rolname LIKE 'rds\\_admin\\_%'"
        ).fetchall():
            su.execute(f'DROP ROLE IF EXISTS "{role}"')


@pytest.fixture
def world(fake_aws):
    """No database needed: for tests of the validation rules."""
    return World(fake_aws, "db.example.internal", 5432, "school", "school_admin").build()


@pytest.fixture
def pg_world(fake_aws):
    """A REAL PostgreSQL database owned by a non-superuser administrator, like RDS. Dropped afterwards."""
    if not SUPERUSER_DSN:
        pytest.skip("set TEST_PG_SUPERUSER_DSN")
    purge_leftovers()  # an aborted earlier run must not break this one: roles are cluster-wide
    suffix = secrets.token_hex(4)
    dbname, admin = f"bs_{suffix}", f"rds_admin_{suffix}"
    parts = dict(p.split("=", 1) for p in SUPERUSER_DSN.split())
    w = World(fake_aws, parts["host"], int(parts["port"]), dbname, admin)
    with psycopg.connect(SUPERUSER_DSN + " dbname=postgres", autocommit=True) as su:
        # CREATEROLE but NOT superuser: exactly the powers RDS gives its master user (no SUPERUSER, no REPLICATION)
        su.execute(f"CREATE ROLE {admin} LOGIN CREATEROLE PASSWORD '{w.master_password}'")
        su.execute(f"CREATE DATABASE {dbname} OWNER {admin}")
    w.build()
    yield w
    with psycopg.connect(SUPERUSER_DSN + " dbname=postgres", autocommit=True) as su:
        su.execute(f"DROP DATABASE IF EXISTS {dbname} WITH (FORCE)")
        roles = [
            r[0]
            for r in su.execute(
                "SELECT rolname FROM pg_roles WHERE rolname ~ '_(svc|migrator)$' OR rolname = %s", (admin,)
            ).fetchall()
        ]
        for role in roles:
            su.execute(f'DROP OWNED BY "{role}"')  # the roles are cluster-wide, so clean them up too
            su.execute(f'DROP ROLE IF EXISTS "{role}"')
