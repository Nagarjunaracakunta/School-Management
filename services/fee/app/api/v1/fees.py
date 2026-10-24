import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import get_fee_service, require_roles
from app.schemas.common import ErrorResponse, Page
from app.schemas.fee import FeeAssign, FeeOut, FeeStatus, FeeStructureCreate, FeeStructureOut
from app.services.fee_service import FeeService
from app.utils.security import CurrentUser, Role

router = APIRouter(prefix="/api/v1", tags=["fees"])

Service = Annotated[FeeService, Depends(get_fee_service)]
AdminOnly = Annotated[CurrentUser, Depends(require_roles(Role.ADMIN))]
AdminOrParent = Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.PARENT))]
PageNo = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]

ERRORS = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    502: {"model": ErrorResponse, "description": "Student service unavailable"},
}


@router.post("/fee-structures", response_model=FeeStructureOut, status_code=status.HTTP_201_CREATED, responses=ERRORS)
def create_structure(body: FeeStructureCreate, service: Service, admin: AdminOnly):
    return service.create_structure(body, admin)


@router.get("/fee-structures", response_model=Page[FeeStructureOut], responses=ERRORS)
def list_structures(service: Service, admin: AdminOnly, page: PageNo = 1, page_size: PageSize = 50):
    items, total = service.list_structures((page - 1) * page_size, page_size)
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.post("/fees", response_model=FeeOut, status_code=status.HTTP_201_CREATED, responses=ERRORS)
def assign_fee(body: FeeAssign, service: Service, admin: AdminOnly):
    """Charge a student for a fee-structure entry."""
    return service.assign(body, admin)


@router.get("/fees", response_model=Page[FeeOut], responses=ERRORS)
def list_fees(
    service: Service,
    user: AdminOrParent,
    status: FeeStatus | None = None,
    student_id: uuid.UUID | None = None,
    outstanding: Annotated[bool, Query(description="Only fees not fully paid (includes overdue)")] = False,
    page: PageNo = 1,
    page_size: PageSize = 20,
):
    items, total = service.list(
        user,
        student_id=student_id,
        status=status,
        outstanding=outstanding,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/fees/{fee_id}", response_model=FeeOut, responses=ERRORS)
def get_fee(fee_id: uuid.UUID, service: Service, user: AdminOrParent):
    return service.get(fee_id, user)


@router.get("/students/{student_id}/fees", response_model=Page[FeeOut], responses=ERRORS)
def student_fees(
    student_id: uuid.UUID, service: Service, user: AdminOrParent, page: PageNo = 1, page_size: PageSize = 50
):
    items, total = service.for_student(student_id, user, (page - 1) * page_size, page_size)
    return Page(items=items, total=total, page=page, page_size=page_size)
