"""Turns an event into the messages to send. Pure functions: no database, no AWS, easy to test.

All text is plain (no HTML), so a value like an applicant's name can never inject markup.
"""

import re
from dataclasses import dataclass

from app.schemas.events import AbsenceData, AdmissionData, Envelope, OverdueData, Parent, PaymentData

SCHOOL = "School Management Portal"
CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
SMS_MAX = 320


@dataclass(frozen=True)
class Draft:
    channel: str
    recipient: str
    recipient_name: str | None
    recipient_email: str | None
    subject: str
    body: str


def one_line(text: str, limit: int = 200) -> str:
    """Subjects must be a single line: a newline in a name could otherwise forge extra email headers."""
    return re.sub(r"\s+", " ", CONTROL_CHARS.sub("", text)).strip()[:limit]


def _clean(text: str) -> str:
    return CONTROL_CHARS.sub("", text)


def _email(parent: Parent, subject: str, body: str) -> Draft:
    greeting = f"Dear {one_line(parent.name, 120)},\n\n"
    return Draft(
        "EMAIL",
        parent.email.lower(),
        parent.name,
        parent.email.lower(),
        one_line(subject),
        greeting + _clean(body) + f"\n\nRegards,\n{SCHOOL}",
    )


def _sms(parent: Parent, text: str) -> Draft | None:
    if not parent.phone:
        return None
    return Draft("SMS", parent.phone, parent.name, parent.email.lower(), "", one_line(text, SMS_MAX))


def _admission_submitted(d: AdmissionData) -> list[Draft]:
    n = one_line(d.applicant_name, 120)
    return [
        _email(
            p,
            f"Admission application received for {n}",
            f"We have received the admission application for {n} (class applied: {one_line(d.class_applied, 50)}). "
            "We will let you know as soon as it has been reviewed.",
        )
        for p in d.parents
    ]


def _admission_approved(d: AdmissionData) -> list[Draft]:
    n = one_line(d.applicant_name, 120)
    drafts: list[Draft | None] = []
    for p in d.parents:
        drafts.append(
            _email(
                p,
                f"Admission approved for {n}",
                f"We are pleased to tell you that the admission of {n} to {one_line(d.class_applied, 50)} "
                "has been approved. The school office will contact you about the next steps.",
            )
        )
        drafts.append(
            _sms(p, f"{SCHOOL}: admission of {n} ({one_line(d.class_applied, 50)}) is approved. Check your email.")
        )
    return [x for x in drafts if x]


def _admission_rejected(d: AdmissionData) -> list[Draft]:
    n = one_line(d.applicant_name, 120)
    return [
        _email(
            p,
            f"Update on the admission application for {n}",
            f"Thank you for applying. After review we are unable to offer {n} a place at this time. "
            "Please contact the school office if you would like to discuss this.",
        )
        for p in d.parents
    ]


def _payment_completed(d: PaymentData) -> list[Draft]:
    s, fee = one_line(d.student_name, 120), one_line(d.fee_name, 80)
    drafts: list[Draft | None] = []
    for p in d.parents:
        drafts.append(
            _email(
                p,
                f"Payment receipt {one_line(d.receipt_no, 30)}",
                f"We received your payment of INR {d.amount} for {fee} ({s}).\n"
                f"Receipt number: {one_line(d.receipt_no, 30)}\nBalance remaining: INR {d.balance_after}",
            )
        )
        drafts.append(
            _sms(
                p,
                f"{SCHOOL}: received INR {d.amount} for {s} ({fee}). "
                f"Receipt {d.receipt_no}. Balance INR {d.balance_after}.",
            )
        )
    return [x for x in drafts if x]


def _fee_overdue(d: OverdueData) -> list[Draft]:
    s, fee = one_line(d.student_name, 120), one_line(d.fee_name, 80)
    drafts: list[Draft | None] = []
    for p in d.parents:
        drafts.append(
            _email(
                p,
                f"Reminder: {fee} for {s} is overdue",
                f"The fee {fee} for {s} was due on {d.due_date.isoformat()} and INR {d.amount_outstanding} "
                f"is still outstanding ({d.days_overdue} days overdue).\n"
                "If you have already paid, please ignore this message. "
                "Otherwise, please contact the school office or pay through the portal.",
            )
        )
        drafts.append(
            _sms(
                p,
                f"{SCHOOL}: {fee} for {s} is overdue by {d.days_overdue} days. "
                f"INR {d.amount_outstanding} outstanding. Please pay via the portal.",
            )
        )
    return [x for x in drafts if x]


def _attendance_absent(d: AbsenceData) -> list[Draft]:
    s = one_line(d.student_name, 120)
    where = f" ({d.class_name}-{d.section_name})" if d.class_name and d.section_name else ""
    drafts: list[Draft | None] = []
    for p in d.parents:
        drafts.append(
            _email(
                p,
                f"{s} was absent on {d.date.isoformat()}",
                f"{s}{where} was marked absent on {d.date.isoformat()}. "
                "If this is unexpected, please contact the school office.",
            )
        )
        drafts.append(_sms(p, f"{SCHOOL}: {s}{where} was marked absent on {d.date.isoformat()}."))
    return [x for x in drafts if x]


# event type -> (data model, renderer). Adding a notification type = adding one line here + a renderer.
HANDLERS = {
    "admission.submitted": (AdmissionData, _admission_submitted),
    "admission.approved": (AdmissionData, _admission_approved),
    "admission.rejected": (AdmissionData, _admission_rejected),
    "payment.completed": (PaymentData, _payment_completed),
    "attendance.absent": (AbsenceData, _attendance_absent),
    "fee.overdue": (OverdueData, _fee_overdue),
}


def render(envelope: Envelope) -> list[Draft] | None:
    """Messages for this event, or None when the event type is not one we notify about."""
    handler = HANDLERS.get(envelope.event_type)
    if handler is None:
        return None
    model, renderer = handler
    return renderer(model.model_validate(envelope.data))
