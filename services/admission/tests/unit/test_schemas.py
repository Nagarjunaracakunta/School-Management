from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from app.schemas.admission import AdmissionCreate, AdmissionUpdate


def test_valid_payload_is_accepted(valid_payload):
    assert AdmissionCreate(**valid_payload).applicant_name == "Asha Rao"


def test_name_is_stripped(valid_payload):
    valid_payload["applicant_name"] = "  Asha Rao  "
    assert AdmissionCreate(**valid_payload).applicant_name == "Asha Rao"


@pytest.mark.parametrize("phone", ["abc", "123", "+91 (98) 76", ""])
def test_bad_phone_is_rejected(valid_payload, phone):
    valid_payload["parents"][0]["phone"] = phone
    with pytest.raises(ValidationError):
        AdmissionCreate(**valid_payload)


def test_needs_at_least_one_parent(valid_payload):
    valid_payload["parents"] = []
    with pytest.raises(ValidationError):
        AdmissionCreate(**valid_payload)


@pytest.mark.parametrize("years", [0, 1, 40])
def test_implausible_age_is_rejected(valid_payload, years):
    valid_payload["date_of_birth"] = (date.today() - timedelta(days=365 * years)).isoformat()
    with pytest.raises(ValidationError):
        AdmissionCreate(**valid_payload)


def test_update_needs_something():
    with pytest.raises(ValidationError):
        AdmissionUpdate()
