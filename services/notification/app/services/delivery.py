import datetime as dt
import logging
import uuid

from sqlalchemy.orm import Session, sessionmaker

from app.messaging.senders import Sender, mask
from app.repositories.notification_repository import NotificationRepository

logger = logging.getLogger(__name__)


class Deliverer:
    """Sends ONE notification and records the outcome. Used by both the SQS worker and the API."""

    def __init__(self, session_factory: sessionmaker[Session], sender: Sender, max_attempts: int) -> None:
        self._session_factory = session_factory
        self._sender = sender
        self._max_attempts = max_attempts

    def deliver(self, notification_id: uuid.UUID, max_attempts: int | None = None) -> str | None:
        """Returns the new status, or None when the row was not PENDING or is being sent by another worker.

        The row stays locked while we call SNS. That is deliberate: it is what prevents a duplicate send.
        The call is short and bounded by the SDK timeouts.
        """
        limit = max_attempts or self._max_attempts
        with self._session_factory() as session:
            repo = NotificationRepository(session)
            n = repo.lock_pending(notification_id)
            if n is None:
                return None
            n.attempts += 1
            try:
                n.provider_message_id = self._sender.send(n)
                n.status, n.sent_at, n.last_error = "SENT", dt.datetime.now(dt.UTC), None
            except Exception as exc:
                n.last_error = f"{type(exc).__name__}: {exc}"[:500]
                n.status = "FAILED" if n.attempts >= limit else "PENDING"
                logger.warning(
                    "notification delivery failed",
                    extra={
                        "notification_id": str(n.id),
                        "channel": n.channel,
                        "recipient": mask(n.recipient),
                        "attempt": n.attempts,
                        "final": n.status == "FAILED",
                        "error": n.last_error,
                    },
                )
            session.commit()
            return n.status
