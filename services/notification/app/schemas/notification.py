import datetime as dt
import re
import uuid
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, EmailStr, StringConstraints, TypeAdapter, model_validator

PHONE_RE = re.compile(r"^\+?[0-9][0-9 \-]{6,18}$")
_email = TypeAdapter(EmailStr)


class Channel(StrEnum):
    EMAIL = "EMAIL"
    SMS = "SMS"


class Status(StrEnum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"


class NotificationCreate(BaseModel):
    """A one-off message written by an admin (for example an announcement to a single parent)."""

    channel: Channel
    recipient: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=254)]
    subject: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] = ""
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]

    @model_validator(mode="after")
    def _check_channel_rules(self) -> "NotificationCreate":
        if self.channel is Channel.EMAIL:
            _email.validate_python(self.recipient)  # raises a validation error for a bad address
            if not self.subject:
                raise ValueError("subject is required for EMAIL")
        else:
            if not PHONE_RE.match(self.recipient):
                raise ValueError("recipient must be a phone number for SMS")
            if len(self.message) > 320:
                raise ValueError("SMS message is limited to 320 characters")
        return self


class NotificationOut(BaseModel):
    id: uuid.UUID
    event_id: uuid.UUID | None
    event_type: str
    channel: Channel
    recipient: str
    recipient_name: str | None
    subject: str
    message: str
    status: Status
    attempts: int
    last_error: str | None  # shown to admins only
    created_at: dt.datetime
    sent_at: dt.datetime | None
