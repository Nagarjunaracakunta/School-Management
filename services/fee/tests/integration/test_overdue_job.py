import datetime as dt
import json
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest

from app.jobs.overdue_reminders import queue_overdue_reminders
from app.models.fee import Fee, OutboxEvent

NOW = dt.datetime(2026, 10, 24, 3, 0, tzinfo=dt.UTC)
TODAY = NOW.date()


@pytest.fixture
def factory(client):
    return client.app.state.session_factory


def make_fee(
    factory, *, due_days_ago=10, status="PENDING", paid="0", parents="default", last_reminded=None, name="Tuition"
) -> uuid.UUID:
    contacts = (
        [{"name": "Ravi Rao", "email": "ravi@example.com", "phone": "+91 98765 43210"}]
        if parents == "default"
        else parents
    )
    with factory() as s:
        structure_id = uuid.uuid4()
        from app.models.fee import FeeStructure

        s.add(
            FeeStructure(
                id=structure_id,
                name=f"{name}-{structure_id.hex[:6]}",
                class_id=uuid.uuid4(),
                class_name="Grade 3",
                academic_year="2026-27",
                amount=Decimal("1000"),
                due_date=TODAY - dt.timedelta(days=due_days_ago),
            )
        )
        s.flush()
        fee = Fee(
            student_id=uuid.uuid4(),
            student_name="Asha Rao",
            structure_id=structure_id,
            name=name,
            amount_due=Decimal("1000"),
            amount_paid=Decimal(paid),
            due_date=TODAY - dt.timedelta(days=due_days_ago),
            status=status,
            parents=contacts,
            last_reminded_at=last_reminded,
        )
        s.add(fee)
        s.commit()
        return fee.id


def events(factory):
    with factory() as s:
        return [e.payload for e in s.query(OutboxEvent).filter(OutboxEvent.event_type == "fee.overdue").all()]


def run(factory, **kw):
    return queue_overdue_reminders(factory, today=TODAY, now=NOW, **kw)


def test_an_overdue_unpaid_fee_gets_a_reminder_with_everything_the_message_needs(factory):
    fee_id = make_fee(factory, due_days_ago=10, status="PARTIAL", paid="400")
    assert run(factory) == 1
    (event,) = events(factory)
    assert event["fee_id"] == str(fee_id) and event["student_name"] == "Asha Rao" and event["fee_name"] == "Tuition"
    assert (
        event["amount_outstanding"] == "600.00"
        and event["days_overdue"] == 10
        and event["due_date"] == (TODAY - dt.timedelta(days=10)).isoformat()
    )
    assert event["parents"][0]["email"] == "ravi@example.com"
    with factory() as s:
        stored = s.get(Fee, fee_id).last_reminded_at
        stored = (
            stored if stored.tzinfo else stored.replace(tzinfo=dt.UTC)
        )  # SQLite drops the zone; PostgreSQL returns it
        assert stored == NOW  # the same instant, whatever zone it is displayed in


def test_fees_that_need_no_reminder_are_left_alone(factory):
    make_fee(factory, status="PAID", paid="1000")  # settled
    make_fee(factory, due_days_ago=-5)  # not due yet
    make_fee(factory, due_days_ago=0)  # due today is not overdue
    assert run(factory) == 0 and events(factory) == []


def test_a_fee_reminded_recently_is_skipped_and_an_old_reminder_is_repeated(factory):
    recent = make_fee(factory, last_reminded=NOW - dt.timedelta(days=3), name="Recent")
    stale = make_fee(factory, last_reminded=NOW - dt.timedelta(days=8), name="Stale")
    assert run(factory) == 1
    assert [e["fee_id"] for e in events(factory)] == [str(stale)] and recent != stale


def test_running_the_job_twice_does_not_remind_twice(factory):
    make_fee(factory)
    assert run(factory) == 1
    assert run(factory) == 0
    assert len(events(factory)) == 1


def test_fees_without_contacts_are_skipped_and_never_marked_as_reminded(factory):
    fee_id = make_fee(factory, parents=None)
    assert run(factory) == 0
    with factory() as s:
        assert s.get(Fee, fee_id).last_reminded_at is None  # nothing pretended to be sent


def test_one_run_is_capped_and_the_next_run_continues_where_it_stopped(factory):
    for i in range(5):
        make_fee(factory, due_days_ago=10 + i, name=f"F{i}")
    assert run(factory, batch=3) == 3
    assert run(factory, batch=3) == 2
    assert len(events(factory)) == 5


def test_the_oldest_debt_is_reminded_first(factory):
    older = make_fee(factory, due_days_ago=40, name="Older")
    make_fee(factory, due_days_ago=5, name="Newer")
    run(factory, batch=1)
    assert [e["fee_id"] for e in events(factory)] == [str(older)]


def test_the_event_reaches_the_queue_through_the_normal_relay(client, factory):
    make_fee(factory)
    run(factory)
    sent = []
    client.app.state.relay._publisher = type("P", (), {"publish": lambda self, t, b: sent.append((t, json.loads(b)))})()
    assert client.app.state.relay.publish_pending() == 1
    event_type, envelope = sent[0]
    assert event_type == "fee.overdue" and envelope["source"] == "fee-service" and envelope["event_id"]


def test_assigning_a_fee_remembers_the_parents_contacts(client, admin, students, make_structure):
    student = students.add_student()
    structure = make_structure()
    r = client.post("/api/v1/fees", json={"student_id": student["id"], "structure_id": structure["id"]}, headers=admin)
    assert r.status_code == 201
    with client.app.state.session_factory() as s:
        fee = s.get(Fee, uuid.UUID(r.json()["id"]))
        assert fee.parents == [{"name": "Ravi Rao", "email": "ravi@example.com", "phone": "+91 98765 43210"}]


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL", "").startswith("postgresql"), reason="needs PostgreSQL")
def test_two_overlapping_runs_remind_every_fee_exactly_once(factory):
    for i in range(12):
        make_fee(factory, due_days_ago=10 + i, name=f"F{i}")
    barrier = threading.Barrier(4)

    def job(_):
        barrier.wait()
        return run(factory, batch=4)

    with ThreadPoolExecutor(4) as pool:
        total = sum(pool.map(job, range(4)))
    ids = [e["fee_id"] for e in events(factory)]
    assert total == 12 == len(ids) == len(set(ids))
