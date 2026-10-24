"""Needs PostgreSQL: skipped on the default in-memory SQLite."""

import os
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.models.admission import OutboxEvent
from app.services.outbox_relay import OutboxRelay

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL", "").startswith("postgresql"), reason="needs PostgreSQL"
)


def test_several_relays_never_publish_the_same_event_twice(client, auth, valid_payload, publisher):
    for i in range(25):
        valid_payload["applicant_name"] = f"Student {i}"
        client.post("/api/v1/admissions", json=valid_payload, headers=auth(sub="p1", role="parent"))

    session_factory = client.app.state.session_factory
    relays = [OutboxRelay(session_factory, publisher, batch_size=10, interval=1) for _ in range(4)]
    barrier = threading.Barrier(len(relays))

    def drain(relay):
        barrier.wait()
        total = 0
        while (sent := relay.publish_pending()) > 0:
            total += sent
        return total

    with ThreadPoolExecutor(len(relays)) as pool:
        counts = list(pool.map(drain, relays))

    ids = [__import__("json").loads(body)["event_id"] for _, body in publisher.sent]
    assert sum(counts) == 25 and len(ids) == 25 and len(set(ids)) == 25  # all sent, none twice
    with session_factory() as session:
        assert session.query(OutboxEvent).filter(OutboxEvent.published_at.is_(None)).count() == 0
