"""Operator commands.   python -m app.cli create-admin --email you@school.org --name "Your Name"

Solves the chicken-and-egg problem: only an admin can create users, so the FIRST admin has to come from
outside the HTTP API. In Kubernetes this runs once as a Job; the password is injected from Secrets Manager
as AUTH_ADMIN_PASSWORD. It is never accepted as a command-line argument (arguments show up in process lists
and shell history).
"""

import argparse
import getpass
import os
import sys

from sqlalchemy.orm import Session, sessionmaker

from app.config.database import build_engine, build_session_factory
from app.config.settings import Settings, get_settings
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.services.passwords import PasswordHasher, password_problem


def create_admin(
    session_factory: sessionmaker[Session], hasher: PasswordHasher, email: str, name: str, password: str
) -> str:
    email = email.strip().lower()
    problem = password_problem(password, email)
    if problem:
        raise SystemExit(problem)
    with session_factory() as session:
        repo = UserRepository(session)
        if repo.by_email(email):
            raise SystemExit(f"A user with the email {email} already exists; nothing changed")
        user = User(email=email, full_name=name, role="admin", password_hash=hasher.hash(password))
        repo.add(user)
        repo.commit()
        return str(user.id)


def main(argv: list[str] | None = None, settings: Settings | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    admin = sub.add_parser("create-admin", help="create the first administrator")
    admin.add_argument("--email", required=True)
    admin.add_argument("--name", required=True)
    args = parser.parse_args(argv)

    settings = settings or get_settings()
    password = os.environ.get("AUTH_ADMIN_PASSWORD") or getpass.getpass("Password for the new admin: ")
    user_id = create_admin(
        build_session_factory(build_engine(settings)), PasswordHasher(settings), args.email, args.name, password
    )
    print(f"Created admin {args.email} ({user_id})", file=sys.stderr)


if __name__ == "__main__":
    main()
