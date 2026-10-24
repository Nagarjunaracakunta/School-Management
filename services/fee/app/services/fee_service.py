import logging
import uuid
from collections.abc import Callable
from datetime import date

from app.clients.student_client import StudentClient
from app.models.fee import Fee, FeeStructure
from app.repositories.fee_repository import FeeRepository
from app.schemas.fee import FeeAssign, FeeOut, FeeStatus, FeeStructureCreate, FeeStructureOut
from app.services.access import visible_student_ids
from app.utils.errors import ConflictError, NotFoundError
from app.utils.security import CurrentUser, Role

logger = logging.getLogger(__name__)


def effective_status(fee: Fee, today: date) -> FeeStatus:
    if fee.status != FeeStatus.PAID and fee.due_date < today:
        return FeeStatus.OVERDUE
    return FeeStatus(fee.status)


def fee_out(fee: Fee, today: date) -> FeeOut:
    return FeeOut(
        id=fee.id,
        student_id=fee.student_id,
        student_name=fee.student_name,
        structure_id=fee.structure_id,
        name=fee.name,
        amount_due=fee.amount_due,
        amount_paid=fee.amount_paid,
        outstanding=fee.outstanding,
        due_date=fee.due_date,
        status=effective_status(fee, today),
    )


def structure_out(s: FeeStructure) -> FeeStructureOut:
    return FeeStructureOut.model_validate(s, from_attributes=True)


class FeeService:
    def __init__(self, repo: FeeRepository, students: StudentClient, clock: Callable[[], date] = date.today) -> None:
        self.repo = repo
        self.students = students
        self.today = clock

    # --- fee structures (admin) ------------------------------------------------------
    def create_structure(self, data: FeeStructureCreate, admin: CurrentUser) -> FeeStructureOut:
        class_name = self.students.list_classes(admin.token).get(str(data.class_id))
        if class_name is None:
            raise NotFoundError("Class not found")
        if self.repo.structure_exists(data.class_id, data.academic_year, data.name):
            raise ConflictError(f"'{data.name}' already exists for {class_name} in {data.academic_year}")
        structure = FeeStructure(
            name=data.name,
            class_id=data.class_id,
            class_name=class_name,
            academic_year=data.academic_year,
            amount=data.amount,
            due_date=data.due_date,
        )
        self.repo.add(structure)
        self.repo.commit()
        return structure_out(structure)

    def list_structures(self, offset: int, limit: int) -> tuple[list[FeeStructureOut], int]:
        rows, total = self.repo.page(
            FeeStructure, order_by=(FeeStructure.academic_year.desc(), FeeStructure.name), offset=offset, limit=limit
        )
        return [structure_out(r) for r in rows], total

    # --- fees --------------------------------------------------------------------------
    def assign(self, data: FeeAssign, admin: CurrentUser) -> FeeOut:
        student = self.students.get_student(str(data.student_id), admin.token)
        if student["status"] != "ACTIVE":
            raise ConflictError("Fees can only be assigned to ACTIVE students")
        structure = self.repo.get(FeeStructure, data.structure_id)
        if structure is None:
            raise NotFoundError("Fee structure not found")
        if self.repo.fee_exists(data.student_id, data.structure_id):
            raise ConflictError("This fee is already assigned to the student")
        fee = Fee(
            student_id=data.student_id,
            student_name=student["name"],
            structure_id=structure.id,
            name=structure.name,
            amount_due=data.amount or structure.amount,
            due_date=structure.due_date,
            parents=[{"name": p["name"], "email": p["email"], "phone": p["phone"]} for p in student.get("parents", [])]
            or None,
        )
        self.repo.add(fee)
        self.repo.commit()
        logger.info("fee assigned", extra={"fee_id": str(fee.id), "student_id": str(data.student_id)})
        return fee_out(fee, self.today())

    def get(self, fee_id: uuid.UUID, user: CurrentUser) -> FeeOut:
        fee = self.repo.get(Fee, fee_id)
        if fee is None:
            raise NotFoundError("Fee not found")
        self._require_student_access(fee.student_id, user, "Fee not found")
        return fee_out(fee, self.today())

    def list(
        self,
        user: CurrentUser,
        *,
        student_id: uuid.UUID | None,
        status: FeeStatus | None,
        outstanding: bool,
        offset: int,
        limit: int,
    ) -> tuple[list[FeeOut], int]:
        allowed = visible_student_ids(self.students, user)
        if student_id is not None:
            if allowed is not None and student_id not in allowed:
                return [], 0  # asking for a child that is not yours looks like "no fees"
            allowed = [student_id]
        if allowed == []:
            return [], 0
        rows, total = self.repo.search_fees(
            today=self.today(), student_ids=allowed, status=status, outstanding=outstanding, offset=offset, limit=limit
        )
        return [fee_out(f, self.today()) for f in rows], total

    def for_student(self, student_id: uuid.UUID, user: CurrentUser, offset: int, limit: int):
        self.students.get_student(str(student_id), user.token)  # 404 if the caller may not see this child
        return self.list(user, student_id=student_id, status=None, outstanding=False, offset=offset, limit=limit)

    def _require_student_access(self, student_id: uuid.UUID, user: CurrentUser, message: str) -> dict | None:
        if user.role is Role.ADMIN:
            return None
        try:
            return self.students.get_student(str(student_id), user.token)
        except NotFoundError as exc:
            raise NotFoundError(message) from exc
