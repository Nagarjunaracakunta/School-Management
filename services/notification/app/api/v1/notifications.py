import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import get_current_user, get_notification_service, require_roles
from app.schemas.common import ErrorResponse, Page
from app.schemas.notification import Channel, NotificationCreate, NotificationOut
from app.schemas.notification import Status as NotificationStatus
from app.services.notification_service import NotificationService
from app.utils.security import CurrentUser, Role

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])

Service = Annotated[NotificationService, Depends(get_notification_service)]
AnyUser = Annotated[CurrentUser, Depends(get_current_user)]
AdminOnly = Annotated[CurrentUser, Depends(require_roles(Role.ADMIN))]

ERRORS = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
}


@router.post("", response_model=NotificationOut, status_code=status.HTTP_201_CREATED, responses=ERRORS)
def send_notification(body: NotificationCreate, service: Service, admin: AdminOnly, response: Response):
    """Send a one-off message now. The result's `status` tells you whether it was handed to SNS (SENT) or failed."""
    created = service.create_manual(body, admin)
    response.headers["Location"] = f"/api/v1/notifications/{created.id}"
    return created


@router.get("", response_model=Page[NotificationOut], responses=ERRORS)
def list_notifications(
    service: Service,
    user: AnyUser,
    status: NotificationStatus | None = None,
    channel: Channel | None = None,
    event_type: Annotated[str | None, Query(max_length=80)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    items, total = service.list(
        user,
        status=status.value if status else None,
        channel=channel.value if channel else None,
        event_type=event_type,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/{notification_id}", response_model=NotificationOut, responses=ERRORS)
def get_notification(notification_id: uuid.UUID, service: Service, user: AnyUser):
    return service.get(notification_id, user)


@router.post("/{notification_id}/retry", response_model=NotificationOut, responses=ERRORS)
def retry_notification(notification_id: uuid.UUID, service: Service, admin: AdminOnly):
    """Re-send a FAILED (or stuck PENDING) notification. One attempt; check `status` in the response."""
    return service.retry(notification_id, admin)
