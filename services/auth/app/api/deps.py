from collections.abc import Callable, Iterator
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config.database import session_scope
from app.config.settings import Settings
from app.repositories.user_repository import UserRepository
from app.services.auth_service import AuthService
from app.services.user_service import UserService
from app.utils.errors import ForbiddenError, UnauthorizedError
from app.utils.security import CurrentUser, Role, decode_token

bearer = HTTPBearer(auto_error=False)  # we raise our own error so the body matches our format


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Iterator[Session]:
    yield from session_scope(request.app.state.session_factory)


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> CurrentUser:
    if credentials is None:
        raise UnauthorizedError("Missing bearer token")
    return decode_token(credentials.credentials, settings)


def require_roles(*roles: Role) -> Callable[[CurrentUser], CurrentUser]:
    def checker(user: Annotated[CurrentUser, Depends(get_current_user)]) -> CurrentUser:
        if user.role not in roles:
            raise ForbiddenError("You do not have permission to perform this action")
        return user

    return checker


def get_auth_service(request: Request, session: Annotated[Session, Depends(get_db)]) -> AuthService:
    s = request.app.state
    return AuthService(UserRepository(session), s.hasher, s.issuer, s.settings)


def get_user_service(request: Request, session: Annotated[Session, Depends(get_db)]) -> UserService:
    return UserService(UserRepository(session), request.app.state.hasher)
