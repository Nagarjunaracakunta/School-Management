"""Needs PostgreSQL: skipped on the default in-memory SQLite."""

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.models.notification import Notification

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL", "").startswith("postgresql"), reason="needs PostgreSQL"
)


class SlowSender:
    """Takes long enough that concurrent workers overlap inside send()."""

    def __init__(self) -> None:
        self.calls = 0
        self._lock = threading.Lock()

    def send(self, notification) -> str:
        with self._lock:
            self.calls += 1
        time.sleep(0.3)
        return "msg-1"


def test_two_workers_given_the_same_duplicate_message_send_it_once(client, event):
    from app.messaging.factory import build_deliverer
    from app.services.event_processor import EventProcessor

    sender = SlowSender()
    session_factory = client.app.state.session_factory
    deliverer = build_deliverer(client.app.state.settings, session_factory, sender)
    processor = EventProcessor(session_factory, deliverer)
    body = event("admission.submitted")  # two parents -> two emails
    barrier = threading.Barrier(5)

    def worker(_):
        barrier.wait()
        return processor.handle(body)

    with ThreadPoolExecutor(5) as pool:
        list(pool.map(worker, range(5)))

    with session_factory() as session:
        rows = session.query(Notification).all()
    assert len(rows) == 2 and all(r.status == "SENT" and r.attempts == 1 for r in rows)
    assert sender.calls == 2  # five workers, two recipients: two sends in total
