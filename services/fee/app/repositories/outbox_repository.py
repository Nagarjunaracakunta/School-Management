from datetime import UTC, datetime

from sqlalchemy import select

from app.models.fee import OutboxEvent
from app.repositories.base import BaseRepository


class OutboxRepository(BaseRepository):
    def add_event(self, event_type: str, payload: dict) -> None:
        self.session.add(OutboxEvent(event_type=event_type, payload=payload))

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
