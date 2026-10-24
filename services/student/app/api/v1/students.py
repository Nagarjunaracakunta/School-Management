import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import JSONResponse

from app.api.deps import get_current_user, get_student_service, require_roles
from app.schemas.common import ErrorResponse, Page
from app.schemas.student import (
    EnrollmentCreate,
    EnrollmentOut,
    StudentCreate,
    StudentOut,
    StudentStatus,
    StudentUpdate,
)
from app.services.student_service import StudentService
from app.utils.security import CurrentUser, Role

router = APIRouter(prefix="/api/v1/students", tags=["students"])

Service = Annotated[StudentService, Depends(get_student_service)]
AnyUser = Annotated[CurrentUser, Depends(get_current_user)]
AdminOnly = Annotated[CurrentUser, Depends(require_roles(Role.ADMIN))]

ERRORS = {
    401: {"model": ErrorResponse, "description": "Missing or invalid token"},
    403: {"model": ErrorResponse, "description": "Role not allowed"},
    404: {"model": ErrorResponse, "description": "Not found"},
}


@router.post("", response_model=StudentOut, status_code=status.HTTP_201_CREATED, responses=ERRORS)
def create_student(body: StudentCreate, service: Service, admin: AdminOnly, response: Response):
    """Idempotent for admissions: repeating the same `admission_ref` returns 200 and the existing student."""
    student, created = service.create(body, admin)
    location = f"/api/v1/students/{student.id}"
    if not created:
        return JSONResponse(status_code=200, content=student.model_dump(mode="json"), headers={"Location": location})
    response.headers["Location"] = location
    return student


@router.get("", response_model=Page[StudentOut], responses=ERRORS)
def list_students(
    service: Service,
    user: AnyUser,
    status: StudentStatus | None = None,
    class_id: uuid.UUID | None = None,
    section_id: uuid.UUID | None = None,
    admission_ref: uuid.UUID | None = None,
    q: Annotated[str | None, Query(max_length=120, description="Search by name")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    items, total = service.list(
        user,
        page=page,
        page_size=page_size,
        status=status.value if status else None,
        class_id=class_id,
        section_id=section_id,
        admission_ref=admission_ref,
        name=q,
    )
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/{student_id}", response_model=StudentOut, responses=ERRORS)
def get_student(student_id: uuid.UUID, service: Service, user: AnyUser):
    return service.get(student_id, user)


@router.put("/{student_id}", response_model=StudentOut, responses=ERRORS)
def update_student(student_id: uuid.UUID, body: StudentUpdate, service: Service, admin: AdminOnly):
    return service.update(student_id, body, admin)


@router.post(
    "/{student_id}/enrollments",
    response_model=EnrollmentOut,
    status_code=status.HTTP_201_CREATED,
    responses={**ERRORS, 409: {"model": ErrorResponse}},
)
def enroll_student(student_id: uuid.UUID, body: EnrollmentCreate, service: Service, admin: AdminOnly):
    return service.enroll(student_id, body)


@router.get("/{student_id}/enrollments", response_model=list[EnrollmentOut], responses=ERRORS)
def list_enrollments(student_id: uuid.UUID, service: Service, user: AnyUser):
    return service.enrollments(student_id, user)
