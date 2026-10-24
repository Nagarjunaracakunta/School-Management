"""Creates the per-service database schemas and roles inside RDS. Safe to run again at any time.

It runs as a Kubernetes Job (a Helm hook, before the services are deployed) using the RDS-managed administrator login.
For each service it makes:   a schema,   a MIGRATOR role (may change tables in that schema),
                             an APP role (may only read and write rows),   and sets their passwords from Secrets Manager.
The passwords are the ones Terraform generated into Secrets Manager, so after this runs, the secrets and the database agree.
Run it again after rotating a secret and the database follows.

What it deliberately refuses to do: set a password for any role whose name is not exactly <service>_svc or
<service>_migrator. A mistaken or tampered secret that says "username: school_admin" must never be able to change the
administrator's password.

Configuration (all environment variables; none of them is a secret):
  MASTER_SECRET_ARN         the RDS-managed administrator login (username + password)
  DB_APP_SECRET_ARNS        JSON: {"fee": "arn:...", ...}   runtime logins
  DB_MIGRATOR_SECRET_ARNS   JSON: {"fee": "arn:...", ...}   schema-changing logins
  BOOTSTRAP_SSLMODE         default "require" (RDS accepts only encrypted connections)
"""

import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass

import boto3
import psycopg
from psycopg import sql

logger = logging.getLogger("db-bootstrap")

SERVICES = ("auth", "admission", "student", "fee", "attendance", "notification")
CONNECT_ATTEMPTS = 6


class BootstrapError(Exception):
    """A problem with the configuration or the secrets. Raised before the database is touched where possible."""


@dataclass(frozen=True)
class Login:
    username: str
    password: str


@dataclass(frozen=True)
class Plan:
    host: str
    port: int
    dbname: str
    master: Login
    apps: dict[str, Login]
    migrators: dict[str, Login]


def _secret_json(arn: str) -> dict:
    if not arn.startswith("arn:aws:secretsmanager:"):
        raise BootstrapError(f"not a Secrets Manager ARN: {arn!r}")
    try:
        client = boto3.client("secretsmanager", region_name=arn.split(":")[3])
        return json.loads(client.get_secret_value(SecretId=arn)["SecretString"])
    except Exception as exc:  # name the problem, never the contents
        raise BootstrapError(f"could not read secret {arn}: {type(exc).__name__}") from exc


def _arn_map(name: str, environ: dict) -> dict[str, str]:
    try:
        mapping = json.loads(environ[name])
    except KeyError as exc:
        raise BootstrapError(f"{name} is not set") from exc
    except json.JSONDecodeError as exc:
        raise BootstrapError(f"{name} is not valid JSON") from exc
    if not isinstance(mapping, dict) or not mapping:
        raise BootstrapError(f"{name} must be a JSON object of service -> ARN")
    return mapping


def build_plan(environ: dict) -> Plan:
    """Reads and CHECKS every secret. Nothing in the database is touched yet."""
    app_arns, migrator_arns = _arn_map("DB_APP_SECRET_ARNS", environ), _arn_map("DB_MIGRATOR_SECRET_ARNS", environ)
    if set(app_arns) != set(migrator_arns):
        raise BootstrapError("DB_APP_SECRET_ARNS and DB_MIGRATOR_SECRET_ARNS must list the same services")
    unknown = sorted(set(app_arns) - set(SERVICES))
    if unknown:
        raise BootstrapError(f"unknown service(s): {', '.join(unknown)}")

    apps: dict[str, Login] = {}
    migrators: dict[str, Login] = {}
    where: set[tuple] = set()
    for service in sorted(app_arns):
        for kind, arns, target, expected in (
            ("app", app_arns, apps, f"{service}_svc"),
            ("migrator", migrator_arns, migrators, f"{service}_migrator"),
        ):
            data = _secret_json(arns[service])
            missing = [k for k in ("username", "password", "host", "port", "dbname") if not data.get(k)]
            if missing:
                raise BootstrapError(f"the {kind} secret for {service} lacks: {', '.join(missing)}")
            if data["username"] != expected:
                # THE safety rule: we only ever set passwords for the roles we own.
                raise BootstrapError(
                    f"the {kind} secret for {service} names the role {data['username']!r}; it must be exactly {expected!r}"
                )
            if len(data["password"]) < 16:
                raise BootstrapError(f"the {kind} password for {service} is too short (under 16 characters)")
            target[service] = Login(data["username"], data["password"])
            where.add((data["host"], int(data["port"]), data["dbname"]))
    if len(where) != 1:
        raise BootstrapError("the secrets point at different databases")
    host, port, dbname = where.pop()

    master = _secret_json(environ["MASTER_SECRET_ARN"]) if environ.get("MASTER_SECRET_ARN") else None
    if not master or not master.get("username") or not master.get("password"):
        raise BootstrapError("MASTER_SECRET_ARN is missing or does not hold a username and password")
    return Plan(host, port, dbname, Login(master["username"], master["password"]), apps, migrators)


def _connect(plan: Plan, login: Login, sslmode: str) -> psycopg.Connection:
    last = None
    for attempt in range(1, CONNECT_ATTEMPTS + 1):  # a database that was just created or modified may take a moment
        try:
            return psycopg.connect(
                host=plan.host,
                port=plan.port,
                dbname=plan.dbname,
                user=login.username,
                password=login.password,
                sslmode=sslmode,
                connect_timeout=10,
                autocommit=True,
            )
        except psycopg.OperationalError as exc:
            last = exc
            logger.warning("connection as %s failed (attempt %d/%d)", login.username, attempt, CONNECT_ATTEMPTS)
            time.sleep(min(2**attempt, 30) if attempt < CONNECT_ATTEMPTS else 0)
    raise BootstrapError(f"could not connect as {login.username}: {type(last).__name__}") from last


def _ident(name: str) -> sql.Identifier:
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,40}", name):
        raise BootstrapError(f"unsafe identifier {name!r}")
    return sql.Identifier(name)


def apply_as_administrator(plan: Plan, sslmode: str) -> None:
    """Roles, schemas, passwords and grants. One transaction: all of it, or none of it."""
    db = _ident(plan.dbname)
    with _connect(plan, plan.master, sslmode) as conn, conn.transaction():
        # Nobody gets anything just for existing; each role is granted exactly what it needs below.
        conn.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(db))
        conn.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
        for service in sorted(plan.apps):
            schema = _ident(service)
            for login in (plan.migrators[service], plan.apps[service]):
                role = _ident(login.username)
                exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (login.username,)).fetchone()
                if not exists:
                    conn.execute(sql.SQL("CREATE ROLE {} LOGIN").format(role))
                # ALTER ... PASSWORD takes a literal, not a parameter, so the value is quoted by the driver itself
                conn.execute(sql.SQL("ALTER ROLE {} WITH LOGIN PASSWORD {}").format(role, sql.Literal(login.password)))
                # Code never names its schema: the role's search_path resolves "applications" to "admission.applications".
                conn.execute(sql.SQL("ALTER ROLE {} SET search_path = {}").format(role, schema))
                conn.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(db, role))
            migrator, app = _ident(plan.migrators[service].username), _ident(plan.apps[service].username)
            conn.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(schema))
            # The migrator may create and change tables here, but it does not own the schema and cannot drop it.
            conn.execute(sql.SQL("GRANT ALL ON SCHEMA {} TO {}").format(schema, migrator))
            conn.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(schema, app))
    logger.info("roles and schemas ready for: %s", ", ".join(sorted(plan.apps)))


def apply_as_migrators(plan: Plan, sslmode: str) -> None:
    """What the app role may do with tables. Run AS the migrator, because default privileges describe the objects that
    role will create. (An administrator without superuser rights cannot set them on another role's behalf, as on RDS.)"""
    for service in sorted(plan.apps):
        schema, app = _ident(service), _ident(plan.apps[service].username)
        with _connect(plan, plan.migrators[service], sslmode) as conn:
            # Tables created from now on ...
            conn.execute(
                sql.SQL("ALTER DEFAULT PRIVILEGES IN SCHEMA {} GRANT SELECT, INSERT, UPDATE ON TABLES TO {}").format(schema, app)
            )
            conn.execute(
                sql.SQL("ALTER DEFAULT PRIVILEGES IN SCHEMA {} GRANT USAGE, SELECT ON SEQUENCES TO {}").format(schema, app)
            )
            # ... and ones that already exist (a re-run after migrations). No DELETE, no DDL: these services never delete rows.
            conn.execute(sql.SQL("GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA {} TO {}").format(schema, app))
            conn.execute(sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {} TO {}").format(schema, app))
    logger.info("table privileges set for: %s", ", ".join(sorted(plan.apps)))


def run(environ: dict | None = None) -> None:
    environ = dict(os.environ if environ is None else environ)
    sslmode = environ.get("BOOTSTRAP_SSLMODE", "require")
    plan = build_plan(environ)  # every secret is checked before the first SQL statement
    apply_as_administrator(plan, sslmode)
    apply_as_migrators(plan, sslmode)
    logger.info("database bootstrap finished")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format='{"time":"%(asctime)s","level":"%(levelname)s","message":"%(message)s"}')
    for noisy in ("botocore", "boto3", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    try:
        run()
    except BootstrapError as exc:
        logger.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
