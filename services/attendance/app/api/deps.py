from collections.abc import Callable, Iterator
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.clients.student_client import StudentClient
from app.config.database import session_scope
from app.config.settings import Settings
from app.repositories.attendance_repository import AttendanceRepository
from app.services.attendance_service import AttendanceService
from app.utils.errors import ForbiddenError, UnauthorizedError
from app.utils.security import CurrentUser, Role, decode_token

bearer = HTTPBearer(auto_error=False)  # we raise our own error so the body matches our format


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Iterator[Session]:
    yield from session_scope(request.app.state.session_factory)


def get_student_client(request: Request) -> StudentClient:
    return request.app.state.student_client


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


def get_attendance_service(
    session: Annotated[Session, Depends(get_db)],
    students: Annotated[StudentClient, Depends(get_student_client)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> AttendanceService:
    return AttendanceService(AttendanceRepository(session), students, settings.attendance_edit_window_days)
