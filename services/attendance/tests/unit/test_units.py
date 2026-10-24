import httpx
import pytest
from pydantic import ValidationError

from app.clients.student_client import HttpStudentClient
from app.schemas.attendance import AttendanceMark, BulkMark
from app.utils.errors import NotFoundError, UpstreamError

ID = "00000000-0000-0000-0000-000000000001"
ID2 = "00000000-0000-0000-0000-000000000002"


def test_subject_type_defaults_to_student():
    mark = AttendanceMark(subject_id=ID, date="2026-10-01", status="PRESENT")
    assert mark.subject_type.value == "student"


@pytest.mark.parametrize("status", ["present", "SICK", ""])
def test_unknown_status_rejected(status):
    with pytest.raises(ValidationError):
        AttendanceMark(subject_id=ID, date="2026-10-01", status=status)


def test_bulk_rejects_duplicates_empty_and_oversized():
    base = {"section_id": ID, "date": "2026-10-01"}
    with pytest.raises(ValidationError):
        BulkMark(**base, records=[{"student_id": ID, "status": "PRESENT"}, {"student_id": ID, "status": "ABSENT"}])
    with pytest.raises(ValidationError):
        BulkMark(**base, records=[])
    too_many = [{"student_id": f"00000000-0000-0000-0000-{i:012d}", "status": "PRESENT"} for i in range(101)]
    with pytest.raises(ValidationError):
        BulkMark(**base, records=too_many)


def _client(handler) -> HttpStudentClient:
    return HttpStudentClient("http://student", 1.0, transport=httpx.MockTransport(handler))


def test_section_roster_filters_by_section_and_walks_pages():
    seen = []

    def handler(request):
        seen.append(dict(request.url.params))
        page = int(request.url.params["page"])
        return httpx.Response(200, json={"items": [{"id": f"s{page}"}], "total": 2})

    roster = _client(handler).list_section_students("sec-1", "tok")
    assert [s["id"] for s in roster] == ["s1", "s2"]
    assert seen[0]["section_id"] == "sec-1" and seen[0]["status"] == "ACTIVE"


def test_get_student_maps_404():
    with pytest.raises(NotFoundError):
        _client(lambda r: httpx.Response(404, json={})).get_student("x", "tok")


@pytest.mark.parametrize(
    "handler",
    [
        lambda r: httpx.Response(500, text="boom"),
        lambda r: httpx.Response(403, json={}),
        lambda r: (_ for _ in ()).throw(httpx.ConnectError("refused")),
        lambda r: (_ for _ in ()).throw(httpx.ReadTimeout("slow")),
    ],
)
def test_failures_become_upstream_error(handler):
    c = _client(handler)
    for call in (
        lambda: c.get_student("x", "t"),
        lambda: c.list_student_ids("t"),
        lambda: c.list_section_students("s", "t"),
        lambda: c.list_teachers("t"),
    ):
        with pytest.raises(UpstreamError):
            call()
