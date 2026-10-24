import datetime as dt
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import JSONResponse

from app.api.deps import get_attendance_service, require_roles
from app.schemas.attendance import (
    AttendanceMark,
    AttendanceOut,
    AttendanceStatus,
    BulkMark,
    BulkResult,
    StudentReportRow,
    SubjectType,
    SummaryOut,
)
from app.schemas.common import ErrorResponse, Page
from app.services.attendance_service import AttendanceService
from app.utils.security import CurrentUser, Role

router = APIRouter(prefix="/api/v1", tags=["attendance"])

Service = Annotated[AttendanceService, Depends(get_attendance_service)]
Staff = Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.TEACHER))]
AnyRole = Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.TEACHER, Role.PARENT))]
PageNo = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]
DateFrom = Annotated[dt.date | None, Query(description="Inclusive start date")]
DateTo = Annotated[dt.date | None, Query(description="Inclusive end date")]

ERRORS = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
    502: {"model": ErrorResponse, "description": "Student service unavailable"},
}


@router.post("/attendance", response_model=AttendanceOut, status_code=status.HTTP_201_CREATED, responses=ERRORS)
def mark_attendance(body: AttendanceMark, service: Service, user: Staff, response: Response):
    """Mark one person for one day. 201 when new; 200 when it corrects an existing record."""
    record, created = service.mark(body, user)
    if not created:
        return JSONResponse(status_code=200, content=record.model_dump(mode="json"))
    response.headers["Location"] = f"/api/v1/students/{record.subject_id}/attendance"
    return record


@router.post("/attendance/bulk", response_model=BulkResult, responses=ERRORS)
def mark_section(body: BulkMark, service: Service, user: Staff):
    """Mark a whole section for one day. All records are saved, or none."""
    return service.mark_bulk(body, user)


@router.get("/attendance", response_model=Page[AttendanceOut], responses=ERRORS)
def list_attendance(
    service: Service,
    user: AnyRole,
    subject_type: SubjectType | None = None,
    status: AttendanceStatus | None = None,
    date_from: DateFrom = None,
    date_to: DateTo = None,
    page: PageNo = 1,
    page_size: PageSize = 20,
):
    items, total = service.list(
        user,
        subject_type=subject_type,
        status=status,
        date_from=date_from,
        date_to=date_to,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/attendance/summary", response_model=SummaryOut, responses=ERRORS)
def attendance_summary(service: Service, user: AnyRole, day: Annotated[dt.date, Query(alias="date")]):
    """Student counts for one day (the dashboard card), limited to what the caller may see."""
    return service.summary(day, user)


@router.get("/attendance/reports/students", response_model=Page[StudentReportRow], responses=ERRORS)
def student_report(
    service: Service,
    user: Staff,
    date_from: Annotated[dt.date, Query()],
    date_to: Annotated[dt.date, Query()],
    class_name: Annotated[str | None, Query(max_length=50)] = None,
    section_name: Annotated[str | None, Query(max_length=20)] = None,
    page: PageNo = 1,
    page_size: PageSize = 50,
):
    """Per-student attendance percentage over a date range (maximum 366 days)."""
    items, total = service.report(
        user,
        date_from=date_from,
        date_to=date_to,
        class_name=class_name,
        section_name=section_name,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/students/{student_id}/attendance", response_model=Page[AttendanceOut], responses=ERRORS)
def student_attendance(
    student_id: uuid.UUID,
    service: Service,
    user: AnyRole,
    date_from: DateFrom = None,
    date_to: DateTo = None,
    page: PageNo = 1,
    page_size: PageSize = 31,
):
    items, total = service.for_student(
        student_id, user, date_from=date_from, date_to=date_to, offset=(page - 1) * page_size, limit=page_size
    )
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/teachers/{teacher_id}/attendance", response_model=Page[AttendanceOut], responses=ERRORS)
def teacher_attendance(
    teacher_id: uuid.UUID,
    service: Service,
    user: Staff,
    date_from: DateFrom = None,
    date_to: DateTo = None,
    page: PageNo = 1,
    page_size: PageSize = 31,
):
    items, total = service.for_teacher(
        teacher_id, user, date_from=date_from, date_to=date_to, offset=(page - 1) * page_size, limit=page_size
    )
    return Page(items=items, total=total, page=page, page_size=page_size)
