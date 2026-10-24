from datetime import date

import pytest
from pydantic import ValidationError

from app.config.settings import Settings, default_academic_year


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2026, 10, 24), "2026-27"),
        (date(2027, 3, 31), "2026-27"),
        (date(2027, 4, 1), "2027-28"),
        (date(2099, 5, 1), "2099-00"),
    ],
)
def test_academic_year_runs_april_to_march(day, expected):
    assert default_academic_year(day) == expected


def test_settings_require_database_and_key():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, jwt_public_key="k")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url="sqlite://")
