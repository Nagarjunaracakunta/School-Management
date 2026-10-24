import pytest
from pydantic import ValidationError

from app.messaging.senders import mask
from app.messaging.sqs_worker import retry_delay
from app.schemas.events import Envelope
from app.schemas.notification import NotificationCreate
from app.services.templates import SMS_MAX, one_line, render
from tests.conftest import EVENTS, PARENTS, make_event


def drafts_for(event_type: str, **overrides):
    envelope = Envelope.model_validate_json(make_event(event_type, {**EVENTS[event_type], **overrides}))
    return render(envelope)


@pytest.mark.parametrize(
    ("event_type", "emails", "sms"),
    [
        ("admission.submitted", 2, 0),
        ("admission.approved", 2, 2),
        ("admission.rejected", 2, 0),
        ("payment.completed", 2, 2),
        ("attendance.absent", 2, 2),
        ("fee.overdue", 2, 2),
    ],
)
def test_each_event_produces_the_expected_messages(event_type, emails, sms):
    drafts = drafts_for(event_type)
    assert sum(d.channel == "EMAIL" for d in drafts) == emails
    assert sum(d.channel == "SMS" for d in drafts) == sms
    assert all("{" not in d.body and "}" not in d.body for d in drafts)  # no unfilled placeholders


def test_payment_message_contains_the_facts_a_parent_needs():
    email = next(d for d in drafts_for("payment.completed") if d.channel == "EMAIL")
    for fact in ("6000.00", "9000.00", "RCT-20261024-AB12CD34", "Tuition Term 1", "Asha Rao"):
        assert fact in email.body
    assert email.recipient == "ravi@example.com" and email.recipient_email == "ravi@example.com"


def test_sms_goes_to_the_phone_but_is_linked_to_the_parents_email():
    sms = next(d for d in drafts_for("attendance.absent") if d.channel == "SMS")
    assert sms.recipient == "+91 98765 43210" and sms.recipient_email == "ravi@example.com"
    assert "2026-10-24" in sms.body and "Grade 3-A" in sms.body


def test_parent_without_a_phone_gets_email_only():
    parents = [{"name": "No Phone", "email": "np@example.com"}]
    drafts = drafts_for("payment.completed", parents=parents)
    assert [d.channel for d in drafts] == ["EMAIL"]


def test_newlines_in_names_cannot_forge_headers_or_break_sms():
    nasty = "Asha\r\nBcc: attacker@evil.com\x00"
    drafts = drafts_for("admission.approved", applicant_name=nasty)
    for d in drafts:
        assert "\n" not in d.subject and "\r" not in d.subject and "\x00" not in d.body


def test_sms_is_capped():
    drafts = drafts_for("admission.approved", applicant_name="A" * 120, class_applied="B" * 50)
    assert all(len(d.body) <= SMS_MAX for d in drafts if d.channel == "SMS")


def test_unknown_event_types_are_ignored_not_errors():
    envelope = Envelope.model_validate_json(make_event("grade.published", {"anything": 1}))
    assert render(envelope) is None


def test_missing_fields_fail_validation():
    envelope = Envelope.model_validate_json(make_event("payment.completed", {"receipt_no": "x"}))
    with pytest.raises(ValidationError):
        render(envelope)


def test_extra_fields_from_producers_are_ignored():
    assert drafts_for("attendance.absent", brand_new_field={"nested": True})


def test_helpers():
    assert one_line("a\n\n  b\t c") == "a b c"
    assert mask("ravi@example.com") == "r***@example.com"
    assert mask("+91 98765 43210").endswith("3210") and "9876" not in mask("+91 98765 43210")
    assert [retry_delay(n, 30, 900) for n in (1, 2, 3, 6, 10)] == [30, 60, 120, 900, 900]


@pytest.mark.parametrize(
    "body",
    [
        {"channel": "EMAIL", "recipient": "not-an-email", "subject": "s", "message": "m"},
        {"channel": "EMAIL", "recipient": "a@b.com", "message": "m"},  # subject required
        {"channel": "SMS", "recipient": "a@b.com", "message": "m"},
        {"channel": "SMS", "recipient": "+91 98765 43210", "message": "x" * 321},
        {"channel": "FAX", "recipient": "1", "message": "m"},
        {"channel": "SMS", "recipient": "+91 98765 43210", "message": ""},
    ],
)
def test_manual_notification_validation(body):
    with pytest.raises(ValidationError):
        NotificationCreate(**body)


def test_valid_manual_notifications():
    assert NotificationCreate(channel="EMAIL", recipient="a@b.com", subject="Hi", message="m")
    assert NotificationCreate(channel="SMS", recipient="+91 98765 43210", message="m")


def test_parent_fixture_data_is_what_templates_expect():
    assert PARENTS[0]["email"] == "ravi@example.com"


def test_the_overdue_reminder_states_the_amount_the_date_and_how_late_it_is():
    email = next(d for d in drafts_for("fee.overdue") if d.channel == "EMAIL")
    for fact in ("9000.00", "2026-10-01", "23 days overdue", "Tuition Term 1", "Asha Rao"):
        assert fact in email.body, fact
    assert "overdue" in email.subject.lower()
    sms = next(d for d in drafts_for("fee.overdue") if d.channel == "SMS")
    assert "9000.00" in sms.body and "23 days" in sms.body and len(sms.body) <= SMS_MAX


def test_an_overdue_event_with_a_bad_date_is_rejected_not_guessed():
    envelope = Envelope.model_validate_json(
        make_event("fee.overdue", {**EVENTS["fee.overdue"], "due_date": "last week"})
    )
    with pytest.raises(ValidationError):
        render(envelope)
