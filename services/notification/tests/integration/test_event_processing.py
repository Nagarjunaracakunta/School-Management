import uuid

import pytest

from app.repositories.notification_repository import NotificationRepository
from app.services.event_processor import Outcome, PoisonMessage

EVENT_ID = "11111111-1111-1111-1111-111111111111"


def rows(client, event_id=None):
    with client.app.state.session_factory() as session:
        from sqlalchemy import select

        from app.models.notification import Notification

        stmt = select(Notification)
        if event_id:
            stmt = stmt.where(Notification.event_id == uuid.UUID(event_id))
        return list(session.scalars(stmt))


def test_payment_event_sends_email_and_sms_to_each_parent(client, processor, event, sender):
    assert processor.handle(event("payment.completed", EVENT_ID)) is Outcome.DONE
    assert len(sender.sent) == 4
    saved = rows(client, EVENT_ID)
    assert {(n.channel, n.status, n.attempts) for n in saved} == {("EMAIL", "SENT", 1), ("SMS", "SENT", 1)}
    assert all(n.provider_message_id and n.sent_at and n.event_type == "payment.completed" for n in saved)


def test_redelivered_event_creates_and_sends_nothing_new(client, processor, event, sender):
    body = event("attendance.absent", EVENT_ID)
    processor.handle(body)
    sent_after_first = len(sender.sent)
    assert processor.handle(body) is Outcome.DONE  # SQS delivered it again
    assert len(sender.sent) == sent_after_first
    assert len(rows(client, EVENT_ID)) == 4


def test_failed_delivery_is_retried_then_succeeds(client, processor, event, sender):
    body = event("admission.submitted", EVENT_ID)
    sender.fail = True
    assert processor.handle(body) is Outcome.RETRY  # message must stay in the queue
    assert {(n.status, n.attempts) for n in rows(client)} == {("PENDING", 1)}

    sender.fail = False
    assert processor.handle(body) is Outcome.DONE
    assert {(n.status, n.attempts) for n in rows(client)} == {("SENT", 2)}
    assert len(rows(client)) == 2  # no duplicate rows from the retry


def test_one_failing_recipient_does_not_resend_the_others(client, processor, event, sender):
    body = event("admission.approved", EVENT_ID)
    sender.fail_recipients = {"sita@example.com"}
    assert processor.handle(body) is Outcome.RETRY
    sent_first = len(sender.sent)  # ravi's email + both SMS are out
    assert sent_first == 3

    sender.fail_recipients = set()
    assert processor.handle(body) is Outcome.DONE
    assert len(sender.sent) == sent_first + 1  # only sita's email was sent now


def test_gives_up_after_max_attempts_and_keeps_the_error(client, processor, event, sender):
    body = event("admission.rejected", EVENT_ID)
    sender.fail = True
    assert [processor.handle(body) for _ in range(3)] == [Outcome.RETRY, Outcome.RETRY, Outcome.DONE]
    saved = rows(client)
    assert {(n.status, n.attempts) for n in saved} == {("FAILED", 3)}
    assert "SNS unavailable" in saved[0].last_error
    assert processor.handle(body) is Outcome.DONE  # FAILED rows are not retried automatically


def test_unknown_event_type_is_acknowledged_and_ignored(client, processor, sender):
    from tests.conftest import make_event

    assert processor.handle(make_event("grade.published", {"x": 1})) is Outcome.DONE
    assert not sender.sent and not rows(client)


@pytest.mark.parametrize(
    "body",
    [
        "not json at all",
        "{}",
        '{"event_id": "not-a-uuid", "event_type": "x", "occurred_at": "2026-01-01T00:00:00Z",'
        ' "source": "s", "data": {}}',
    ],
)
def test_malformed_messages_are_poison(processor, body):
    with pytest.raises(PoisonMessage):
        processor.handle(body)


def test_known_event_with_missing_fields_is_poison(processor):
    from tests.conftest import make_event

    with pytest.raises(PoisonMessage):
        processor.handle(make_event("payment.completed", {"receipt_no": "only-this"}))


def test_concurrent_creation_of_the_same_rows_is_tolerated(client, processor, event, sender, monkeypatch):
    """Two workers get the same event at once: the second one's INSERT hits the unique key and must recover."""
    body = event("admission.submitted", EVENT_ID)
    real = NotificationRepository.for_event
    calls = {"n": 0}

    def blind_first_time(self, event_id):
        calls["n"] += 1
        if calls["n"] == 1:
            processor.handle(body)  # "the other worker" wins the race
            return []  # ...and we did not see its rows yet
        return real(self, event_id)

    monkeypatch.setattr(NotificationRepository, "for_event", blind_first_time)
    assert processor.handle(body) is Outcome.DONE
    assert len(rows(client)) == 2 and len(sender.sent) == 2
