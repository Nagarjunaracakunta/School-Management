"""Guards the migrations. The same file lives in every service.

- Always runs: there must be exactly one migration head (two heads = a merge conflict someone forgot).
- Needs PostgreSQL (TEST_DATABASE_URL): the migrations apply, produce exactly what the models describe,
  and roll back cleanly. If you change a model and forget the migration, this test fails.
"""

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from app.models.base import Base

SERVICE_ROOT = Path(__file__).resolve().parents[2]
BASE_URL = os.getenv("TEST_DATABASE_URL", "")
needs_postgres = pytest.mark.skipif(not BASE_URL.startswith("postgresql"), reason="needs PostgreSQL")


def alembic_config() -> Config:
    cfg = Config(str(SERVICE_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(SERVICE_ROOT / "migrations"))  # independent of the working directory
    return cfg


def test_there_is_exactly_one_migration_head():
    assert len(ScriptDirectory.from_config(alembic_config()).get_heads()) == 1


@pytest.fixture
def scratch_schema(monkeypatch):
    """An empty schema of its own, so this test never touches the tables other tests use."""
    schema = "migration_check"
    admin = create_engine(BASE_URL)
    with admin.begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        conn.execute(text(f"CREATE SCHEMA {schema}"))
    url = make_url(BASE_URL).update_query_dict({"options": f"-csearch_path={schema}"})
    monkeypatch.setenv("DATABASE_URL", url.render_as_string(hide_password=False))
    engine = create_engine(url)
    yield engine
    engine.dispose()
    with admin.begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
    admin.dispose()


@needs_postgres
def test_migrations_produce_exactly_what_the_models_describe(scratch_schema):
    command.upgrade(alembic_config(), "head")
    with scratch_schema.connect() as conn:
        differences = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata)
    assert differences == [], f"models and migrations disagree: {differences}"


@needs_postgres
def test_migrations_can_be_repeated_and_rolled_back(scratch_schema):
    cfg = alembic_config()
    command.upgrade(cfg, "head")
    command.upgrade(cfg, "head")  # running again is a no-op, not an error (deploys retry)
    command.downgrade(cfg, "base")
    assert inspect(scratch_schema).get_table_names() == ["alembic_version"]
