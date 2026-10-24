import httpx
import pytest

from app.clients.student_client import HttpStudentClient
from app.utils.errors import UpstreamError

URL = "/api/v1/admissions"


def approved(client, auth, payload, sub="p1", role="parent") -> dict:
    created = client.post(URL, json=payload, headers=auth(sub=sub, role=role)).json()
    client.put(f"{URL}/{created['id']}", json={"status": "APPROVED"}, headers=auth())
    return created


def test_enroll_creates_student_and_marks_enrolled(client, auth, valid_payload, students, make_token):
    admission = approved(client, auth, valid_payload)
    token = make_token()
    r = client.post(f"{URL}/{admission['id']}/enroll", headers={"Authorization": f"Bearer {token}"})

    assert r.status_code == 200
    assert r.json()["status"] == "ENROLLED" and r.json()["student_id"] == "22222222-2222-2222-2222-222222222222"
    payload, forwarded_token = students.calls[0]
    assert forwarded_token == token  # caller's identity is forwarded
    assert payload["admission_ref"] == admission["id"] and payload["guardian_user_id"] == "p1"
    assert payload["parents"][0]["email"] == "ravi@example.com"


def test_enroll_is_idempotent(client, auth, valid_payload, students):
    admission = approved(client, auth, valid_payload)
    for _ in range(2):
        assert client.post(f"{URL}/{admission['id']}/enroll", headers=auth()).status_code == 200
    assert len(students.calls) == 1


def test_admin_filed_application_does_not_link_admin_as_parent(client, auth, valid_payload, students):
    admission = approved(client, auth, valid_payload, sub="admin-9", role="admin")
    client.post(f"{URL}/{admission['id']}/enroll", headers=auth())
    assert students.calls[0][0]["guardian_user_id"] is None


def test_only_approved_can_be_enrolled(client, auth, valid_payload, students):
    submitted = client.post(URL, json=valid_payload, headers=auth()).json()
    r = client.post(f"{URL}/{submitted['id']}/enroll", headers=auth())
    assert r.status_code == 409 and not students.calls


def test_only_admin_can_enroll(client, auth, valid_payload):
    admission = approved(client, auth, valid_payload)
    assert client.post(f"{URL}/{admission['id']}/enroll", headers=auth(sub="p1", role="parent")).status_code == 403


def test_student_service_outage_leaves_admission_approved_and_retry_works(client, auth, valid_payload, students):
    admission = approved(client, auth, valid_payload)
    students.down = True
    r = client.post(f"{URL}/{admission['id']}/enroll", headers=auth())
    assert r.status_code == 502 and r.json()["error"]["code"] == "upstream_error"
    assert client.get(f"{URL}/{admission['id']}", headers=auth()).json()["status"] == "APPROVED"

    students.down = False
    assert client.post(f"{URL}/{admission['id']}/enroll", headers=auth()).json()["status"] == "ENROLLED"


def _client(handler) -> HttpStudentClient:
    return HttpStudentClient("http://student", 1.0, transport=httpx.MockTransport(handler))


def test_http_client_sends_auth_and_request_id():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(auth=request.headers["Authorization"], rid=request.headers["X-Request-ID"], url=str(request.url))
        return httpx.Response(201, json={"id": "abc"})

    assert _client(handler).create_student({"name": "x"}, "tok") == {"id": "abc"}
    assert seen["auth"] == "Bearer tok" and seen["rid"] and seen["url"] == "http://student/api/v1/students"


@pytest.mark.parametrize(
    "handler",
    [
        lambda r: httpx.Response(500, text="boom"),
        lambda r: httpx.Response(403, json={}),
        lambda r: (_ for _ in ()).throw(httpx.ConnectError("refused")),
        lambda r: (_ for _ in ()).throw(httpx.ReadTimeout("slow")),
    ],
)
def test_http_client_maps_failures_to_upstream_error(handler):
    with pytest.raises(UpstreamError):
        _client(handler).create_student({}, "tok")
