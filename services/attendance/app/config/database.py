from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config.settings import Settings


def build_engine(settings: Settings) -> Engine:
    url = settings.sqlalchemy_url
    if str(url).startswith("sqlite"):
        # SQLite is for local/tests only. StaticPool keeps one connection for in-memory DBs.
        return create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    # pool_pre_ping drops dead connections (e.g. after an RDS failover) instead of failing a request.
    # The DB role's search_path is set to this service's schema, so models need no schema prefix.
    return create_engine(url, pool_size=settings.db_pool_size, pool_pre_ping=True)


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    session = factory()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
