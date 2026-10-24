import uuid
from typing import Any

from sqlalchemy import func, select

from app.models.notification import Notification
from app.repositories.base import BaseRepository


class NotificationRepository(BaseRepository):
    def for_event(self, event_id: uuid.UUID) -> list[Notification]:
        return list(self.session.scalars(select(Notification).where(Notification.event_id == event_id)))

    def lock_pending(self, notification_id: uuid.UUID) -> Notification | None:
        """Claim a PENDING row. If another worker already holds it, SKIP LOCKED returns nothing, so the
        same message is never sent twice by two workers racing on a duplicate SQS delivery."""
        return self.session.scalar(
            select(Notification)
            .where(Notification.id == notification_id, Notification.status == "PENDING")
            .with_for_update(skip_locked=True)
        )

    def search(
        self,
        *,
        visible_to_email: str | None,
        status: str | None,
        channel: str | None,
        event_type: str | None,
        offset: int,
        limit: int,
    ) -> tuple[list[Notification], int]:
        """`visible_to_email=None` means no restriction (admin)."""
        where: list[Any] = []
        if visible_to_email is not None:
            where.append(Notification.recipient_email == visible_to_email)
        if status:
            where.append(Notification.status == status)
        if channel:
            where.append(Notification.channel == channel)
        if event_type:
            where.append(Notification.event_type == event_type)
        total = self.session.scalar(select(func.count(Notification.id)).where(*where)) or 0
        rows = self.session.scalars(
            select(Notification)
            .where(*where)
            .order_by(Notification.created_at.desc(), Notification.id)
            .offset(offset)
            .limit(limit)
        )
        return list(rows), total
