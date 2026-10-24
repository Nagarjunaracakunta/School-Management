"""Runs the REAL boto3 code against moto, an in-process imitation of SQS and SNS."""

import json
import threading
import time

import boto3
import pytest
from moto import mock_aws

from app.messaging.senders import SnsSender
from app.messaging.sqs_worker import SqsWorker
from app.models.notification import Notification
from app.services.event_processor import EventProcessor

REGION = "ap-south-1"


@pytest.fixture
def aws():
    with mock_aws():
        yield {"sqs": boto3.client("sqs", region_name=REGION), "sns": boto3.client("sns", region_name=REGION)}


def make_worker(aws, queue_url, client, heartbeat=None) -> SqsWorker:
    processor = EventProcessor(client.app.state.session_factory, client.app.state.deliverer)
    return SqsWorker(
        aws["sqs"],
        queue_url,
        processor,
        wait_seconds=0,
        batch_size=10,
        retry_base=30,
        retry_cap=900,
        heartbeat_file=heartbeat,
    )


def counts(aws, url):
    a = aws["sqs"].get_queue_attributes(QueueUrl=url, AttributeNames=["All"])["Attributes"]
    return int(a["ApproximateNumberOfMessages"]), int(a["ApproximateNumberOfMessagesNotVisible"])


def notification_count(client):
    with client.app.state.session_factory() as session:
        return session.query(Notification).count()


def test_message_is_processed_then_deleted(aws, client, event, sender):
    url = aws["sqs"].create_queue(QueueName="events")["QueueUrl"]
    aws["sqs"].send_message(QueueUrl=url, MessageBody=event("payment.completed"))

    assert make_worker(aws, url, client).poll_once() == 1
    assert notification_count(client) == 4 and len(sender.sent) == 4
    assert counts(aws, url) == (0, 0)  # gone for good


def test_failed_delivery_keeps_the_message_and_backs_off(aws, client, event, sender):
    url = aws["sqs"].create_queue(QueueName="events")["QueueUrl"]
    aws["sqs"].send_message(QueueUrl=url, MessageBody=event("admission.submitted"))
    sender.fail = True

    make_worker(aws, url, client).poll_once()
    assert counts(aws, url) == (0, 1)  # still in the queue, hidden until the backoff passes


def test_poison_message_is_kept_not_deleted(aws, client, sender):
    url = aws["sqs"].create_queue(QueueName="events")["QueueUrl"]
    aws["sqs"].send_message(QueueUrl=url, MessageBody="this is not an event")

    make_worker(aws, url, client).poll_once()
    assert counts(aws, url) == (0, 1) and notification_count(client) == 0


def test_poison_message_ends_up_in_the_dead_letter_queue(aws, client):
    dlq = aws["sqs"].create_queue(QueueName="events-dlq")["QueueUrl"]
    dlq_arn = aws["sqs"].get_queue_attributes(QueueUrl=dlq, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
    url = aws["sqs"].create_queue(
        QueueName="events",
        Attributes={
            "VisibilityTimeout": "0",  # redeliver immediately so the test does not wait
            "RedrivePolicy": json.dumps({"deadLetterTargetArn": dlq_arn, "maxReceiveCount": "2"}),
        },
    )["QueueUrl"]
    aws["sqs"].send_message(QueueUrl=url, MessageBody="garbage")

    worker = make_worker(aws, url, client)
    for _ in range(4):
        worker.poll_once()

    assert sum(counts(aws, url)) == 0
    assert counts(aws, dlq)[0] == 1  # waiting for a human, with the original body intact
    assert aws["sqs"].receive_message(QueueUrl=dlq)["Messages"][0]["Body"] == "garbage"


def test_unknown_event_type_is_deleted(aws, client, sender):
    from tests.conftest import make_event

    url = aws["sqs"].create_queue(QueueName="events")["QueueUrl"]
    aws["sqs"].send_message(QueueUrl=url, MessageBody=make_event("grade.published", {"x": 1}))
    make_worker(aws, url, client).poll_once()
    assert counts(aws, url) == (0, 0) and not sender.sent


def test_a_batch_with_good_and_bad_messages_handles_each_separately(aws, client, event, sender):
    url = aws["sqs"].create_queue(QueueName="events")["QueueUrl"]
    for body in (event("attendance.absent"), "garbage", event("admission.rejected")):
        aws["sqs"].send_message(QueueUrl=url, MessageBody=body)

    assert make_worker(aws, url, client).poll_once() == 3
    assert notification_count(client) == 4 + 2  # the two good events were fully processed
    assert counts(aws, url) == (0, 1)  # only the garbage is left


def test_run_loop_processes_and_stops_cleanly(aws, client, event, sender, tmp_path):
    url = aws["sqs"].create_queue(QueueName="events")["QueueUrl"]
    beat = tmp_path / "heartbeat"
    worker = make_worker(aws, url, client, heartbeat=str(beat))
    stop = threading.Event()
    thread = threading.Thread(target=worker.run, args=(stop,))
    thread.start()
    aws["sqs"].send_message(QueueUrl=url, MessageBody=event("payment.completed"))

    # Wait for the QUEUE to drain (the worker deletes a message only after fully handling it). Do not poll the
    # database from this thread: on SQLite both threads share one connection, so a read here could roll back
    # the worker's transaction.
    deadline = time.time() + 15
    while counts(aws, url) != (0, 0) and time.time() < deadline:
        time.sleep(0.05)
    stop.set()
    thread.join(timeout=10)

    assert not thread.is_alive() and notification_count(client) == 4
    assert beat.exists()  # the liveness signal Kubernetes will watch


def test_polling_errors_do_not_kill_the_worker(aws, client):
    worker = make_worker(aws, "https://sqs.ap-south-1.amazonaws.com/000000000000/missing", client)
    stop = threading.Event()
    thread = threading.Thread(target=worker.run, args=(stop,))
    thread.start()
    time.sleep(0.3)
    assert thread.is_alive()  # it logged the error and is backing off
    stop.set()
    thread.join(timeout=10)
    assert not thread.is_alive()


def test_sns_sender_publishes_json_with_filterable_attributes(aws, client):
    topic = aws["sns"].create_topic(Name="notifications")["TopicArn"]
    sink = aws["sqs"].create_queue(QueueName="sink")["QueueUrl"]
    sink_arn = aws["sqs"].get_queue_attributes(QueueUrl=sink, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
    aws["sns"].subscribe(TopicArn=topic, Protocol="sqs", Endpoint=sink_arn)

    n = Notification(
        event_type="payment.completed",
        channel="SMS",
        recipient="+91 98765 43210",
        recipient_name="Ravi",
        subject="",
        body="Received INR 6000.00",
    )
    n.id = __import__("uuid").uuid4()
    message_id = SnsSender(topic, REGION).send(n)

    received = json.loads(aws["sqs"].receive_message(QueueUrl=sink)["Messages"][0]["Body"])
    payload = json.loads(received["Message"])
    assert message_id and payload["channel"] == "SMS" and payload["message"] == "Received INR 6000.00"
    assert payload["notification_id"] == str(n.id) and payload["recipient"] == "+91 98765 43210"
    assert received["MessageAttributes"]["channel"]["Value"] == "SMS"
