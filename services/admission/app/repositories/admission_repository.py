import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.admission import Application, OutboxEvent


class AdmissionRepository:
    """The only place that talks SQL. Services never build queries."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, application: Application) -> None:
        self.session.add(application)
        self.session.flush()  # assigns defaults; nothing is permanent until commit()

    def add_event(self, event_type: str, payload: dict) -> None:
        self.session.add(OutboxEvent(event_type=event_type, payload=payload))

    def get(self, application_id: uuid.UUID) -> Application | None:
        return self.session.get(Application, application_id)

    def search(
        self,
        *,
        submitted_by: str | None,
        status: str | None,
        class_applied: str | None,
        name: str | None,
        offset: int,
        limit: int,
    ) -> tuple[list[Application], int]:
        query = select(Application)
        if submitted_by:
            query = query.where(Application.submitted_by == submitted_by)
        if status:
            query = query.where(Application.status == status)
        if class_applied:
            query = query.where(Application.class_applied == class_applied)
        if name:
            # escape LIKE wildcards in user input so "%" cannot match everything
            escaped = name.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            query = query.where(Application.applicant_name.ilike(f"%{escaped}%", escape="\\"))
        total = self.session.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = self.session.scalars(
            query.order_by(Application.submitted_at.desc(), Application.id).offset(offset).limit(limit)
        ).all()
        return list(rows), total

    def commit(self) -> None:
        self.session.commit()

    # --- outbox -------------------------------------------------------------
    def lock_unpublished(self, limit: int) -> list[OutboxEvent]:
        # SKIP LOCKED lets several pods relay at once without picking the same rows.
        return list(
            self.session.scalars(
                select(OutboxEvent)
                .where(OutboxEvent.published_at.is_(None))
                .order_by(OutboxEvent.created_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )

    @staticmethod
    def mark_published(event: OutboxEvent) -> None:
        event.published_at = datetime.now(UTC)
