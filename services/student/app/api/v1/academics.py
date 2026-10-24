import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import get_academic_service, get_current_user, require_roles
from app.schemas.academic import (
    AssignmentCreate,
    AssignmentOut,
    ClassCreate,
    ClassOut,
    SectionCreate,
    SectionOut,
    SubjectCreate,
    SubjectOut,
    TeacherCreate,
    TeacherOut,
)
from app.schemas.common import ErrorResponse, Page
from app.services.academic_service import AcademicService, section_out
from app.utils.security import CurrentUser, Role

router = APIRouter(prefix="/api/v1", tags=["academics"])

Service = Annotated[AcademicService, Depends(get_academic_service)]
AnyUser = Annotated[CurrentUser, Depends(get_current_user)]
AdminOnly = Annotated[CurrentUser, Depends(require_roles(Role.ADMIN))]
StaffOnly = Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.TEACHER))]

ERRORS = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
}
PageNo = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]


@router.post("/classes", response_model=ClassOut, status_code=status.HTTP_201_CREATED, responses=ERRORS)
def create_class(body: ClassCreate, service: Service, admin: AdminOnly):
    return service.create_class(body)


@router.get("/classes", response_model=Page[ClassOut], responses=ERRORS)
def list_classes(service: Service, user: AnyUser, page: PageNo = 1, page_size: PageSize = 50):
    items, total = service.list_classes((page - 1) * page_size, page_size)
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.post("/sections", response_model=SectionOut, status_code=status.HTTP_201_CREATED, responses=ERRORS)
def create_section(body: SectionCreate, service: Service, admin: AdminOnly):
    return section_out(service.create_section(body))


@router.get("/sections", response_model=Page[SectionOut], responses=ERRORS)
def list_sections(
    service: Service, user: AnyUser, class_id: uuid.UUID | None = None, page: PageNo = 1, page_size: PageSize = 50
):
    items, total = service.list_sections(class_id, (page - 1) * page_size, page_size)
    return Page(items=[section_out(s) for s in items], total=total, page=page, page_size=page_size)


@router.post(
    "/sections/{section_id}/assignments",
    response_model=AssignmentOut,
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
)
def assign_teacher(section_id: uuid.UUID, body: AssignmentCreate, service: Service, admin: AdminOnly):
    return service.assign_teacher(section_id, body)


@router.get("/sections/{section_id}/assignments", response_model=list[AssignmentOut], responses=ERRORS)
def list_assignments(section_id: uuid.UUID, service: Service, user: StaffOnly):
    return service.list_assignments(section_id)


@router.post("/subjects", response_model=SubjectOut, status_code=status.HTTP_201_CREATED, responses=ERRORS)
def create_subject(body: SubjectCreate, service: Service, admin: AdminOnly):
    return service.create_subject(body)


@router.get("/subjects", response_model=Page[SubjectOut], responses=ERRORS)
def list_subjects(service: Service, user: AnyUser, page: PageNo = 1, page_size: PageSize = 50):
    items, total = service.list_subjects((page - 1) * page_size, page_size)
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.post("/teachers", response_model=TeacherOut, status_code=status.HTTP_201_CREATED, responses=ERRORS)
def create_teacher(body: TeacherCreate, service: Service, admin: AdminOnly):
    return service.create_teacher(body)


@router.get("/teachers", response_model=Page[TeacherOut], responses=ERRORS)
def list_teachers(service: Service, user: StaffOnly, page: PageNo = 1, page_size: PageSize = 50):
    items, total = service.list_teachers((page - 1) * page_size, page_size)
    return Page(items=items, total=total, page=page, page_size=page_size)
