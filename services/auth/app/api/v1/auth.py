from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.api.deps import get_auth_service, get_current_user, get_user_service
from app.schemas.auth import LoginRequest, PasswordChange, TokenResponse, UserOut
from app.schemas.common import ErrorResponse
from app.services.auth_service import AuthService
from app.services.user_service import UserService
from app.utils.security import CurrentUser

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

ERRORS = {401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}}


@router.post("/login", response_model=TokenResponse, responses={401: {"model": ErrorResponse}})
def login(body: LoginRequest, service: Annotated[AuthService, Depends(get_auth_service)], response: Response):
    """Exchange email + password for a short-lived access token. Every failure returns the same 401."""
    response.headers["Cache-Control"] = "no-store"  # a token must never be cached by a browser or proxy
    return service.login(str(body.email), body.password)


@router.get("/me", response_model=UserOut, responses=ERRORS)
def me(
    service: Annotated[UserService, Depends(get_user_service)],
    caller: Annotated[CurrentUser, Depends(get_current_user)],
):
    """The caller's CURRENT record from the database (so a deactivated user is noticed, unlike a token)."""
    return service.me(caller)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT, responses=ERRORS)
def change_password(
    body: PasswordChange,
    service: Annotated[UserService, Depends(get_user_service)],
    caller: Annotated[CurrentUser, Depends(get_current_user)],
):
    service.change_own_password(body, caller)
