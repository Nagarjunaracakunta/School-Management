import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import get_current_user, get_user_service, require_roles
from app.schemas.auth import PasswordReset, UserCreate, UserOut, UserRole, UserUpdate
from app.schemas.common import ErrorResponse, Page
from app.services.user_service import UserService
from app.utils.security import CurrentUser, Role

router = APIRouter(prefix="/api/v1/users", tags=["users"])

Service = Annotated[UserService, Depends(get_user_service)]
AdminOnly = Annotated[CurrentUser, Depends(require_roles(Role.ADMIN))]
AnyUser = Annotated[CurrentUser, Depends(get_current_user)]
ERRORS = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED, responses=ERRORS)
def create_user(body: UserCreate, service: Service, admin: AdminOnly, response: Response):
    user = service.create(body, admin)
    response.headers["Location"] = f"/api/v1/users/{user.id}"
    return user


@router.get("", response_model=Page[UserOut], responses=ERRORS)
def list_users(
    service: Service,
    admin: AdminOnly,
    role: UserRole | None = None,
    is_active: bool | None = None,
    q: Annotated[str | None, Query(max_length=120, description="Search name or email")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    items, total = service.list(
        role=role.value if role else None, is_active=is_active, q=q, offset=(page - 1) * page_size, limit=page_size
    )
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/{user_id}", response_model=UserOut, responses=ERRORS)
def get_user(user_id: uuid.UUID, service: Service, caller: AnyUser):
    return service.get(user_id, caller)


@router.put("/{user_id}", response_model=UserOut, responses=ERRORS)
def update_user(user_id: uuid.UUID, body: UserUpdate, service: Service, admin: AdminOnly):
    return service.update(user_id, body, admin)


@router.post("/{user_id}/password", status_code=status.HTTP_204_NO_CONTENT, responses=ERRORS)
def reset_password(user_id: uuid.UUID, body: PasswordReset, service: Service, admin: AdminOnly):
    """Admin sets a new password (and unlocks the account), for example when someone forgot theirs."""
    service.reset_password(user_id, body.new_password, admin)
