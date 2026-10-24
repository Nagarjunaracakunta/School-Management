import json
import logging
from typing import Protocol

import boto3

logger = logging.getLogger(__name__)


class EventPublisher(Protocol):
    def publish(self, event_type: str, body: str) -> None: ...


class SqsPublisher:
    """Sends events to SQS. Credentials come from the pod's IAM role (IRSA), never from keys."""

    def __init__(self, queue_url: str, region: str) -> None:
        self._queue_url = queue_url
        self._client = boto3.client("sqs", region_name=region)

    def publish(self, event_type: str, body: str) -> None:
        self._client.send_message(
            QueueUrl=self._queue_url,
            MessageBody=body,
            MessageAttributes={"event_type": {"DataType": "String", "StringValue": event_type}},
        )


class LogPublisher:
    """Local/dev stand-in: shows what WOULD be sent to SQS."""

    def publish(self, event_type: str, body: str) -> None:
        logger.info("event published (log only)", extra={"event_type": event_type, "event": json.loads(body)})
