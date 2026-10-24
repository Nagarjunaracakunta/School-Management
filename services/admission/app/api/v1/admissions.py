import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import get_admission_service, require_roles
from app.schemas.admission import AdmissionCreate, AdmissionOut, AdmissionStatus, AdmissionUpdate
from app.schemas.common import ErrorResponse, Page
from app.services.admission_service import AdmissionService
from app.utils.security import CurrentUser, Role

router = APIRouter(prefix="/api/v1/admissions", tags=["admissions"])

Service = Annotated[AdmissionService, Depends(get_admission_service)]
AdminOrParent = Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.PARENT))]
AdminOnly = Annotated[CurrentUser, Depends(require_roles(Role.ADMIN))]

ERRORS = {
    401: {"model": ErrorResponse, "description": "Missing or invalid token"},
    403: {"model": ErrorResponse, "description": "Role not allowed"},
    404: {"model": ErrorResponse, "description": "Not found"},
}


@router.post("", response_model=AdmissionOut, status_code=status.HTTP_201_CREATED, responses=ERRORS)
def create_admission(body: AdmissionCreate, service: Service, user: AdminOrParent, response: Response):
    application = service.submit(body, user)
    response.headers["Location"] = f"/api/v1/admissions/{application.id}"
    return application


@router.get("", response_model=Page[AdmissionOut], responses=ERRORS)
def list_admissions(
    service: Service,
    user: AdminOrParent,
    status: AdmissionStatus | None = None,
    class_applied: Annotated[str | None, Query(max_length=50)] = None,
    q: Annotated[str | None, Query(max_length=120, description="Search by applicant name")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    items, total = service.list(
        user, status=status, class_applied=class_applied, name=q, page=page, page_size=page_size
    )
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/{admission_id}", response_model=AdmissionOut, responses=ERRORS)
def get_admission(admission_id: uuid.UUID, service: Service, user: AdminOrParent):
    return service.get(admission_id, user)


@router.post(
    "/{admission_id}/enroll",
    response_model=AdmissionOut,
    responses={**ERRORS, 409: {"model": ErrorResponse}, 502: {"model": ErrorResponse}},
)
def enroll_admission(admission_id: uuid.UUID, service: Service, user: AdminOnly):
    """Creates the student record for an APPROVED admission (idempotent) and marks it ENROLLED."""
    return service.enroll(admission_id, user)


@router.put("/{admission_id}", response_model=AdmissionOut, responses={**ERRORS, 409: {"model": ErrorResponse}})
def review_admission(admission_id: uuid.UUID, body: AdmissionUpdate, service: Service, user: AdminOnly):
    return service.review(admission_id, body, user)
