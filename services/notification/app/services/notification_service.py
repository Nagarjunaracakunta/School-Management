import logging
import uuid

from app.models.notification import Notification
from app.repositories.notification_repository import NotificationRepository
from app.schemas.notification import NotificationCreate, NotificationOut
from app.services.delivery import Deliverer
from app.utils.errors import ConflictError, NotFoundError
from app.utils.security import CurrentUser, Role

logger = logging.getLogger(__name__)


def notification_out(n: Notification, user: CurrentUser) -> NotificationOut:
    return NotificationOut(
        id=n.id,
        event_id=n.event_id,
        event_type=n.event_type,
        channel=n.channel,
        recipient=n.recipient,
        recipient_name=n.recipient_name,
        subject=n.subject,
        message=n.body,
        status=n.status,
        attempts=n.attempts,
        last_error=n.last_error if user.role is Role.ADMIN else None,  # internal errors are not for parents
        created_at=n.created_at,
        sent_at=n.sent_at,
    )


class NotificationService:
    def __init__(self, repo: NotificationRepository, deliverer: Deliverer) -> None:
        self.repo = repo
        self.deliverer = deliverer

    def create_manual(self, data: NotificationCreate, admin: CurrentUser) -> NotificationOut:
        n = Notification(
            event_type="manual",
            channel=data.channel.value,
            recipient=data.recipient.lower() if data.channel.value == "EMAIL" else data.recipient,
            recipient_email=data.recipient.lower() if data.channel.value == "EMAIL" else None,
            subject=data.subject,
            body=data.message,
            created_by=admin.id,
        )
        self.repo.add(n)
        self.repo.commit()
        # One attempt, right now: there is no queue message that would retry it later.
        self.deliverer.deliver(n.id, max_attempts=1)
        self.repo.session.refresh(n)  # the deliverer updated the row in its own session
        return notification_out(n, admin)

    def get(self, notification_id: uuid.UUID, user: CurrentUser) -> NotificationOut:
        n = self._load(notification_id, user)
        return notification_out(n, user)

    def list(
        self,
        user: CurrentUser,
        *,
        status: str | None,
        channel: str | None,
        event_type: str | None,
        offset: int,
        limit: int,
    ) -> tuple[list[NotificationOut], int]:
        # Anyone but an admin sees only messages addressed to their own email (a claim in their token).
        # A token without an email claim therefore sees nothing, which is the safe default.
        if user.role is Role.ADMIN:
            scope: str | None = None
        elif user.email:
            scope = user.email
        else:
            return [], 0
        rows, total = self.repo.search(
            visible_to_email=scope, status=status, channel=channel, event_type=event_type, offset=offset, limit=limit
        )
        return [notification_out(n, user) for n in rows], total

    def retry(self, notification_id: uuid.UUID, admin: CurrentUser) -> NotificationOut:
        n = self._load(notification_id, admin)
        if n.status == "SENT":
            raise ConflictError("This notification was already sent")
        n.status, n.attempts, n.last_error = "PENDING", 0, None
        self.repo.commit()
        self.deliverer.deliver(n.id, max_attempts=1)
        logger.info("notification retried", extra={"notification_id": str(n.id), "by": admin.id})
        self.repo.session.refresh(n)
        return notification_out(n, admin)

    def _load(self, notification_id: uuid.UUID, user: CurrentUser) -> Notification:
        n = self.repo.get(Notification, notification_id)
        hidden = n is not None and user.role is not Role.ADMIN and (not user.email or n.recipient_email != user.email)
        if n is None or hidden:
            raise NotFoundError("Notification not found")  # same answer for "missing" and "not yours"
        return n
