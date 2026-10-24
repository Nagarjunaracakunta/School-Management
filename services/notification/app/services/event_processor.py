import logging
import uuid
from enum import StrEnum

from pydantic import ValidationError
from sqlalchemy.orm import Session, sessionmaker

from app.models.notification import Notification
from app.repositories.notification_repository import NotificationRepository
from app.schemas.events import Envelope
from app.services.delivery import Deliverer
from app.services.templates import Draft, render
from app.utils.errors import ConflictError
from app.utils.request_context import request_id_var

logger = logging.getLogger(__name__)


class Outcome(StrEnum):
    DONE = "done"  # delete the SQS message
    RETRY = "retry"  # keep it: some recipient is still PENDING


class PoisonMessage(Exception):  # noqa: N818
    """The message can never succeed (bad JSON, missing fields). We do not delete it: SQS redelivers it a few
    times and then moves it to the dead-letter queue, where a human can inspect it."""


class EventProcessor:
    def __init__(self, session_factory: sessionmaker[Session], deliverer: Deliverer) -> None:
        self._session_factory = session_factory
        self._deliverer = deliverer

    def handle(self, body: str) -> Outcome:
        try:
            envelope = Envelope.model_validate_json(body)
            drafts = render(envelope)
        except (ValidationError, ValueError) as exc:
            raise PoisonMessage(f"Invalid event: {exc}") from exc

        request_id_var.set(str(envelope.event_id))  # the event id is the correlation id in worker logs
        if drafts is None:
            # A newer producer may emit event types we do not know yet. Not an error: nothing to notify.
            logger.info("ignoring event type", extra={"event_type": envelope.event_type})
            return Outcome.DONE

        ids = self._ensure_rows(envelope, drafts)
        for notification_id in ids:
            self._deliverer.deliver(notification_id)

        with self._session_factory() as session:
            pending = [n for n in NotificationRepository(session).for_event(envelope.event_id) if n.status == "PENDING"]
        logger.info(
            "event processed",
            extra={"event_type": envelope.event_type, "messages": len(ids), "still_pending": len(pending)},
        )
        return Outcome.RETRY if pending else Outcome.DONE

    def _ensure_rows(self, envelope: Envelope, drafts: list[Draft]) -> list[uuid.UUID]:
        """Create any missing rows, so a redelivered event creates nothing new. Returns the ids to deliver."""
        for _ in range(2):  # the second pass handles two workers inserting the same rows at once
            with self._session_factory() as session:
                repo = NotificationRepository(session)
                existing = {(n.recipient, n.channel): n for n in repo.for_event(envelope.event_id)}
                try:
                    for d in drafts:
                        if (d.recipient, d.channel) not in existing:
                            repo.add(
                                Notification(
                                    event_id=envelope.event_id,
                                    event_type=envelope.event_type,
                                    channel=d.channel,
                                    recipient=d.recipient,
                                    recipient_name=d.recipient_name,
                                    recipient_email=d.recipient_email,
                                    subject=d.subject,
                                    body=d.body,
                                )
                            )
                    repo.commit()
                except ConflictError:
                    continue
                return [n.id for n in repo.for_event(envelope.event_id) if n.status == "PENDING"]
        raise RuntimeError("could not create notification rows")
