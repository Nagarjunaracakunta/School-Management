import json
import logging
from typing import Protocol

import boto3

from app.config.settings import Settings
from app.models.notification import Notification

logger = logging.getLogger(__name__)


class Sender(Protocol):
    def send(self, notification: Notification) -> str:
        """Hand the message to the delivery system. Returns a provider message id. Raises on failure."""


def mask(recipient: str) -> str:
    """Logs must not contain full emails or phone numbers (personal data)."""
    if "@" in recipient:
        local, _, domain = recipient.partition("@")
        return f"{local[:1]}***@{domain}"
    return f"{'*' * max(len(recipient) - 4, 0)}{recipient[-4:]}"


class SnsSender:
    """Publishes each message to one SNS topic. SNS fans it out to whatever is subscribed:
    an email/SMS delivery function, an ops mailbox, an archive queue. Adding a new destination
    needs a new subscription in Terraform, not a code change here.

    Note: SNS cannot send email to arbitrary addresses (only to confirmed subscribers). In production
    the email subscriber would be a small function that calls Amazon SES. Here SNS is the boundary.
    """

    def __init__(self, topic_arn: str, region: str) -> None:
        self._topic_arn = topic_arn
        self._client = boto3.client("sns", region_name=region)

    def send(self, notification: Notification) -> str:
        body = {
            "notification_id": str(notification.id),
            "event_type": notification.event_type,
            "channel": notification.channel,
            "recipient": notification.recipient,
            "recipient_name": notification.recipient_name,
            "subject": notification.subject,
            "message": notification.body,
        }
        response = self._client.publish(
            TopicArn=self._topic_arn,
            Message=json.dumps(body),
            # Attributes let subscribers filter (e.g. an SMS function only takes channel=SMS) without parsing the body
            MessageAttributes={
                "channel": {"DataType": "String", "StringValue": notification.channel},
                "event_type": {"DataType": "String", "StringValue": notification.event_type},
            },
        )
        return response["MessageId"]


class LogSender:
    """Local stand-in: shows what WOULD be published."""

    def send(self, notification: Notification) -> str:
        logger.info(
            "notification sent (log only)",
            extra={
                "notification_id": str(notification.id),
                "channel": notification.channel,
                "recipient": mask(notification.recipient),
                "event_type": notification.event_type,
            },
        )
        return f"log-{notification.id}"


def build_sender(settings: Settings) -> Sender:
    return SnsSender(settings.sns_topic_arn, settings.aws_region) if settings.sns_topic_arn else LogSender()
