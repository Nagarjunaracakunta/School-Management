import json
import logging
import threading
import uuid
from datetime import UTC

from sqlalchemy.orm import Session, sessionmaker

from app.repositories.admission_repository import AdmissionRepository
from app.utils.events import EventPublisher
from app.utils.request_context import request_id_var

logger = logging.getLogger(__name__)


class OutboxRelay:
    """Moves committed outbox rows to SQS.

    Delivery is AT LEAST ONCE: if we crash after sending but before marking a row published,
    the event is sent again. Consumers de-duplicate using `event_id`.
    """

    def __init__(
        self, session_factory: sessionmaker[Session], publisher: EventPublisher, batch_size: int, interval: float
    ) -> None:
        self._session_factory = session_factory
        self._publisher = publisher
        self._batch_size = batch_size
        self._interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def publish_pending(self) -> int:
        sent = 0
        with self._session_factory() as session:
            repo = AdmissionRepository(session)
            for event in repo.lock_unpublished(self._batch_size):
                envelope = {
                    "event_id": str(event.id),
                    "event_type": event.event_type,
                    "version": 1,
                    "occurred_at": event.created_at.astimezone(UTC).isoformat(),
                    "source": "admission-service",
                    "data": event.payload,
                }
                request_id_var.set(str(uuid.uuid4()))
                try:
                    self._publisher.publish(event.event_type, json.dumps(envelope))
                except Exception:
                    event.attempts += 1
                    logger.exception("event publish failed", extra={"event_id": str(event.id)})
                    break  # keep order; retry on the next tick
                repo.mark_published(event)
                sent += 1
            session.commit()
        return sent

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.publish_pending()
            except Exception:  # never let the loop die (e.g. DB briefly down)
                logger.exception("outbox relay iteration failed")
            self._stop.wait(self._interval)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="outbox-relay", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
