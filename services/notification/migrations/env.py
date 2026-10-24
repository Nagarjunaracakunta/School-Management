"""Alembic environment.

Connects as the service's MIGRATOR role. The role's search_path points at the service's own schema, so
migrations never name a schema and the same files run unchanged in dev, stage and prod.
"""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.engine import URL

import app.models.notification  # noqa: F401  (registers the tables on Base.metadata)
from app.config import aws_secrets
from app.models.base import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def database_url() -> str | URL:
    # DATABASE_URL wins (tests); otherwise build it from the same DB_* variables the service uses.
    if url := os.environ.get("DATABASE_URL"):
        return url
    # In Kubernetes the migration job is given only the ARN of the schema-changing login and reads the secret itself.
    if arn := os.environ.get("DB_SECRET_ARN"):
        return aws_secrets.db_url_from_secret(arn)
    return URL.create(
        "postgresql+psycopg",
        username=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", "5432")),
        database=os.environ.get("DB_NAME", "school"),
    )


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of running it (alembic upgrade head --sql)."""
    context.configure(url=str(database_url()), target_metadata=target_metadata, literal_binds=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(database_url())
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
