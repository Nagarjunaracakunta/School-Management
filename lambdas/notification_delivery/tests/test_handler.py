"""Runs the real boto3 calls against moto (an in-process imitation of AWS). botocore checks every parameter's name and
type before sending, so a wrong parameter in handler.py fails here instead of in production."""

import json
import os
import sys
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import handler  # noqa: E402

REGION = "ap-south-1"


@pytest.fixture(autouse=True)
def aws(monkeypatch):
    for key, value in {"AWS_ACCESS_KEY_ID": "testing", "AWS_SECRET_ACCESS_KEY": "testing", "AWS_DEFAULT_REGION": REGION}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("FROM_ADDRESS", "no-reply@school.example")
    monkeypatch.delenv("SES_CONFIGURATION_SET", raising=False)
    monkeypatch.delenv("SMS_SENDER_ID", raising=False)
    handler._clients.clear()  # a fresh boto3 client inside each mock
    with mock_aws():
        boto3.client("ses").verify_email_identity(EmailAddress="no-reply@school.example")
        yield
    handler._clients.clear()


def sns_event(**message) -> dict:
    return {"Records": [{"Sns": {"MessageId": "m-1", "Message": json.dumps(message)}}]}


EMAIL = {
    "notification_id": "n-1",
    "event_type": "payment.completed",
    "channel": "EMAIL",
    "recipient": "ravi@example.com",
    "subject": "Payment receipt RCT-1",
    "message": "We received your payment.",
}
SMS = {**EMAIL, "channel": "SMS", "recipient": "+91 98765 43210", "subject": "", "message": "Received INR 6000.00."}


def sent_emails():
    from moto.ses import ses_backends

    return ses_backends["123456789012"][REGION].sent_messages


def test_an_email_message_is_sent_through_ses():
    assert handler.handler(sns_event(**EMAIL)) == {"delivered": 1}
    (sent,) = sent_emails()
    assert sent.source == "no-reply@school.example" and sent.destinations["ToAddresses"] == ["ravi@example.com"]
    assert "Payment receipt RCT-1" in sent.subject and "We received your payment." in sent.body


def test_a_newline_in_the_subject_cannot_inject_headers():
    handler.handler(sns_event(**{**EMAIL, "subject": "Hello\r\nBcc: attacker@evil.com"}))
    (sent,) = sent_emails()
    assert "\n" not in sent.subject and "\r" not in sent.subject


def test_an_sms_message_is_published_with_a_normalised_number():
    published = []
    real = handler.client("sns").publish

    def spy(**kwargs):
        published.append(kwargs)
        return real(**kwargs)

    handler._clients["sns"].publish = spy
    assert handler.handler(sns_event(**SMS)) == {"delivered": 1}
    assert published[0]["PhoneNumber"] == "+919876543210"  # spaces removed: E.164
    assert published[0]["MessageAttributes"]["AWS.SNS.SMS.SMSType"]["StringValue"] == "Transactional"


def test_the_sms_sender_id_is_used_when_configured(monkeypatch):
    monkeypatch.setenv("SMS_SENDER_ID", "SCHOOL")
    published = []
    real = handler.client("sns").publish
    handler._clients["sns"].publish = lambda **kw: (published.append(kw), real(**kw))[1]
    handler.handler(sns_event(**SMS))
    assert published[0]["MessageAttributes"]["AWS.SNS.SMS.SenderID"]["StringValue"] == "SCHOOL"


@pytest.mark.parametrize("phone", ["98765 43210", "+0123456", "abc", "+91", ""])
def test_a_bad_phone_number_fails_loudly(phone):
    with pytest.raises(handler.DeliveryError):
        handler.handler(sns_event(**{**SMS, "recipient": phone}))


@pytest.mark.parametrize("recipient", ["not-an-email", "two@@signs.com", "has space@x.com"])
def test_a_bad_email_address_fails_loudly(recipient):
    with pytest.raises(handler.DeliveryError):
        handler.handler(sns_event(**{**EMAIL, "recipient": recipient}))


def test_missing_configuration_or_fields_fail_loudly(monkeypatch):
    monkeypatch.delenv("FROM_ADDRESS")
    with pytest.raises(handler.DeliveryError, match="FROM_ADDRESS"):
        handler.handler(sns_event(**EMAIL))
    monkeypatch.setenv("FROM_ADDRESS", "no-reply@school.example")
    with pytest.raises(handler.DeliveryError, match="subject"):
        handler.handler(sns_event(**{**EMAIL, "subject": "  "}))
    with pytest.raises(handler.DeliveryError, match="channel"):
        handler.handler(sns_event(**{k: v for k, v in EMAIL.items() if k != "channel"}))
    with pytest.raises(handler.DeliveryError, match="unknown channel"):
        handler.handler(sns_event(**{**EMAIL, "channel": "PIGEON"}))


def test_garbage_input_is_an_error_not_a_silent_success():
    with pytest.raises(Exception):  # noqa: B017
        handler.handler({"Records": [{"Sns": {"MessageId": "m-2", "Message": "this is not json"}}]})


def test_an_unverified_sender_makes_ses_refuse_and_the_error_surfaces():
    os.environ["FROM_ADDRESS"] = "someone-else@school.example"  # never verified with SES
    with pytest.raises(Exception):  # noqa: B017
        handler.handler(sns_event(**EMAIL))


def test_logs_never_contain_the_full_address_or_number(caplog):
    with caplog.at_level("INFO"):
        handler.handler(sns_event(**EMAIL))
        handler.handler(sns_event(**SMS))
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "ravi@example.com" not in text and "98765 43210" not in text and "9876543210" not in text
    assert "r***@example.com" in text and "n-1" in text


def test_the_masking_helpers():
    assert handler.mask("ravi@example.com") == "r***@example.com"
    assert handler.mask("+919876543210").endswith("3210") and "9876" not in handler.mask("+919876543210")
    assert handler.normalize_phone("+91 (98765) 43-210") == "+919876543210"
