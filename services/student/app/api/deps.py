from collections.abc import Callable, Iterator
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config.database import session_scope
from app.config.settings import Settings
from app.repositories.academic_repository import AcademicRepository
from app.repositories.student_repository import StudentRepository
from app.services.academic_service import AcademicService
from app.services.student_service import StudentService
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


def get_student_service(
    session: Annotated[Session, Depends(get_db)], settings: Annotated[Settings, Depends(get_settings_dep)]
) -> StudentService:
    return StudentService(StudentRepository(session, settings.current_academic_year))


def get_academic_service(session: Annotated[Session, Depends(get_db)]) -> AcademicService:
    return AcademicService(AcademicRepository(session))
