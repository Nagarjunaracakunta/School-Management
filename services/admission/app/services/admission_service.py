import logging
import uuid

from app.clients.student_client import StudentClient
from app.models.admission import Application, ApplicationParent
from app.repositories.admission_repository import AdmissionRepository
from app.schemas.admission import AdmissionCreate, AdmissionStatus, AdmissionUpdate
from app.utils.errors import ConflictError, NotFoundError
from app.utils.security import CurrentUser, Role

logger = logging.getLogger(__name__)

S = AdmissionStatus
# Allowed status changes. ENROLLED is intentionally absent: enrollment will be done by the
# Student integration (next phase), not by a manual status edit.
ALLOWED_TRANSITIONS: dict[S, set[S]] = {
    S.SUBMITTED: {S.UNDER_REVIEW, S.APPROVED, S.REJECTED},
    S.UNDER_REVIEW: {S.APPROVED, S.REJECTED},
    S.APPROVED: set(),
    S.REJECTED: set(),
    S.ENROLLED: set(),
}
EVENT_FOR_STATUS = {S.APPROVED: "admission.approved", S.REJECTED: "admission.rejected"}


class AdmissionService:
    """Business rules. Knows nothing about HTTP or SQL."""

    def __init__(self, repo: AdmissionRepository, students: StudentClient) -> None:
        self.repo = repo
        self.students = students

    def submit(self, data: AdmissionCreate, user: CurrentUser) -> Application:
        application = Application(
            applicant_name=data.applicant_name,
            date_of_birth=data.date_of_birth,
            class_applied=data.class_applied,
            status=S.SUBMITTED,
            submitted_by=user.id,
            submitted_by_role=user.role.value,
            parents=[
                ApplicationParent(name=p.name, email=p.email, phone=p.phone, relationship_type=p.relationship)
                for p in data.parents
            ],
        )
        self.repo.add(application)
        self.repo.add_event("admission.submitted", self._event_data(application))
        self.repo.commit()  # application + event are saved together or not at all
        logger.info("admission submitted", extra={"application_id": str(application.id)})
        return application

    def get(self, application_id: uuid.UUID, user: CurrentUser) -> Application:
        application = self.repo.get(application_id)
        # Parents asking for someone else's record get 404, not 403: do not reveal it exists.
        if application is None or not self._can_see(application, user):
            raise NotFoundError("Admission not found")
        return application

    def list(
        self,
        user: CurrentUser,
        *,
        status: AdmissionStatus | None,
        class_applied: str | None,
        name: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[Application], int]:
        return self.repo.search(
            submitted_by=None if user.role is Role.ADMIN else user.id,
            status=status.value if status else None,
            class_applied=class_applied,
            name=name,
            offset=(page - 1) * page_size,
            limit=page_size,
        )

    def review(self, application_id: uuid.UUID, update: AdmissionUpdate, user: CurrentUser) -> Application:
        application = self.get(application_id, user)
        if update.status and update.status.value != application.status:
            current = AdmissionStatus(application.status)
            if update.status not in ALLOWED_TRANSITIONS[current]:
                raise ConflictError(f"Cannot change status from {current} to {update.status}")
            application.status = update.status.value
            if event := EVENT_FOR_STATUS.get(update.status):
                self.repo.add_event(event, self._event_data(application))
        if update.review_notes is not None:
            application.review_notes = update.review_notes
        self.repo.commit()
        logger.info(
            "admission reviewed",
            extra={"application_id": str(application.id), "new_status": application.status, "by": user.id},
        )
        return application

    def enroll(self, application_id: uuid.UUID, user: CurrentUser) -> Application:
        """APPROVED -> ENROLLED by creating the student in the Student Service.

        Safe to retry: the Student Service is idempotent on `admission_ref`. We call it FIRST and
        only then mark ENROLLED, so a failure leaves the admission APPROVED and the admin can retry.
        """
        application = self.get(application_id, user)
        if application.status == S.ENROLLED:
            return application
        if application.status != S.APPROVED:
            raise ConflictError(f"Only APPROVED admissions can be enrolled (current: {application.status})")

        student = self.students.create_student(
            {
                "name": application.applicant_name,
                "date_of_birth": application.date_of_birth.isoformat(),
                "admission_ref": str(application.id),
                # Link the login only if a parent submitted it; an admin filing on a parent's behalf must
                # not become the "parent" of the child.
                "guardian_user_id": application.submitted_by if application.submitted_by_role == "parent" else None,
                "parents": [
                    {"name": p.name, "email": p.email, "phone": p.phone, "relationship": p.relationship_type}
                    for p in application.parents
                ],
            },
            user.token,
        )
        application.student_id = uuid.UUID(student["id"])
        application.status = S.ENROLLED.value
        self.repo.commit()
        logger.info("admission enrolled", extra={"application_id": str(application.id), "student_id": student["id"]})
        return application

    @staticmethod
    def _can_see(application: Application, user: CurrentUser) -> bool:
        return user.role is Role.ADMIN or application.submitted_by == user.id

    @staticmethod
    def _event_data(application: Application) -> dict:
        # Carries what the Notification Service needs, so it never has to call back (loose coupling).
        return {
            "application_id": str(application.id),
            "applicant_name": application.applicant_name,
            "class_applied": application.class_applied,
            "status": application.status,
            "parents": [{"name": p.name, "email": p.email, "phone": p.phone} for p in application.parents],
        }
