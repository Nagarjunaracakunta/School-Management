"""Delivers notifications: SNS topic -> this function -> Amazon SES (email) or Amazon SNS SMS.

The Notification Service publishes one message per recipient per channel to an SNS topic, with the attribute
channel=EMAIL or channel=SMS. SNS cannot email arbitrary addresses by itself, so this function does the last step.

Behaviour worth knowing:
  * SNS delivers AT LEAST ONCE, so on rare occasions the same message can arrive twice (a duplicate email). The
    notification_id is logged so duplicates can be spotted.
  * A message that fails (bad phone number, SES refusal, throttling) raises an error. Lambda retries twice, then
    writes the message to the failure queue, where an alarm tells a human. Nothing is silently dropped.
  * Logs never contain full email addresses or phone numbers.
"""

import json
import logging
import os
import re
from typing import Any

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

E164 = re.compile(r"^\+[1-9][0-9]{6,14}$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_clients: dict[str, Any] = {}


def client(name: str) -> Any:
    """One boto3 client per service, created on first use and reused while the Lambda container stays warm."""
    if name not in _clients:
        _clients[name] = boto3.client(name)
    return _clients[name]


class DeliveryError(Exception):
    """A message that cannot be delivered. Raised so Lambda retries and then parks it in the failure queue."""


def mask(recipient: str) -> str:
    if "@" in recipient:
        local, _, domain = recipient.partition("@")
        return f"{local[:1]}***@{domain}"
    return f"{'*' * max(len(recipient) - 4, 0)}{recipient[-4:]}"


def one_line(text: str, limit: int = 200) -> str:
    """A subject must be a single line, or a newline could smuggle in extra email headers."""
    return re.sub(r"\s+", " ", text).strip()[:limit]


def normalize_phone(raw: str) -> str:
    """'+91 98765 43210' -> '+919876543210'. SNS requires E.164: a plus sign, then digits only."""
    cleaned = re.sub(r"[\s\-().]", "", raw)
    if not E164.match(cleaned):
        raise DeliveryError("recipient is not a valid international phone number")
    return cleaned


def send_email(message: dict[str, Any]) -> str:
    sender = os.environ.get("FROM_ADDRESS")
    if not sender:
        raise DeliveryError("FROM_ADDRESS is not configured; cannot send email")
    to = message["recipient"].strip()
    if not EMAIL.match(to):
        raise DeliveryError("recipient is not a valid email address")
    subject = one_line(message.get("subject") or "")
    if not subject:
        raise DeliveryError("an email needs a subject")

    request: dict[str, Any] = {
        "FromEmailAddress": sender,
        "Destination": {"ToAddresses": [to]},
        "Content": {
            "Simple": {
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {"Text": {"Data": message["message"], "Charset": "UTF-8"}},  # plain text only: no markup injection
            }
        },
    }
    if config_set := os.environ.get("SES_CONFIGURATION_SET"):
        request["ConfigurationSetName"] = config_set  # lets SES report bounces and complaints
    return client("sesv2").send_email(**request)["MessageId"]


def send_sms(message: dict[str, Any]) -> str:
    phone = normalize_phone(message["recipient"])
    attributes = {"AWS.SNS.SMS.SMSType": {"DataType": "String", "StringValue": "Transactional"}}
    if sender_id := os.environ.get("SMS_SENDER_ID"):
        attributes["AWS.SNS.SMS.SenderID"] = {"DataType": "String", "StringValue": sender_id}
    return client("sns").publish(PhoneNumber=phone, Message=message["message"], MessageAttributes=attributes)["MessageId"]


SENDERS = {"EMAIL": send_email, "SMS": send_sms}


def deliver(message: dict[str, Any]) -> str:
    for field in ("channel", "recipient", "message"):
        if not message.get(field):
            raise DeliveryError(f"message has no '{field}'")
    channel = str(message["channel"]).upper()
    sender = SENDERS.get(channel)
    if sender is None:
        raise DeliveryError(f"unknown channel '{channel}'")

    provider_id = sender(message)
    logger.info(
        json.dumps(
            {
                "event": "delivered",
                "channel": channel,
                "notification_id": message.get("notification_id"),
                "event_type": message.get("event_type"),
                "recipient": mask(message["recipient"]),
                "provider_message_id": provider_id,
            }
        )
    )
    return provider_id


def handler(event: dict[str, Any], context: Any = None) -> dict[str, int]:
    records = event.get("Records", [])
    for record in records:
        try:
            message = json.loads(record["Sns"]["Message"])
            deliver(message)
        except Exception:
            # Log the cause (never the message body), then re-raise so Lambda's retry/failure-queue machinery runs.
            logger.exception(json.dumps({"event": "delivery_failed", "sns_message_id": record.get("Sns", {}).get("MessageId")}))
            raise
    return {"delivered": len(records)}
