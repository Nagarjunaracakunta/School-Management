import httpx
import pytest

from app.clients.student_client import HttpStudentClient
from app.utils.errors import NotFoundError, UpstreamError


def client_for(handler) -> HttpStudentClient:
    return HttpStudentClient("http://student", 1.0, transport=httpx.MockTransport(handler))


def test_get_student_sends_token_and_request_id():
    seen = {}

    def handler(request):
        seen.update(auth=request.headers["Authorization"], rid=request.headers["X-Request-ID"])
        return httpx.Response(200, json={"id": "s1"})

    assert client_for(handler).get_student("s1", "tok") == {"id": "s1"}
    assert seen["auth"] == "Bearer tok" and seen["rid"]


def test_404_becomes_not_found():
    with pytest.raises(NotFoundError):
        client_for(lambda r: httpx.Response(404, json={})).get_student("s1", "tok")


@pytest.mark.parametrize(
    "handler",
    [
        lambda r: httpx.Response(500, text="boom"),
        lambda r: httpx.Response(401, json={}),
        lambda r: (_ for _ in ()).throw(httpx.ConnectError("refused")),
        lambda r: (_ for _ in ()).throw(httpx.ReadTimeout("slow")),
    ],
)
def test_failures_become_upstream_error(handler):
    c = client_for(handler)
    for call in (lambda: c.get_student("s1", "t"), lambda: c.list_student_ids("t"), lambda: c.list_classes("t")):
        with pytest.raises(UpstreamError):
            call()


def test_list_student_ids_walks_pages():
    def handler(request):
        page = int(request.url.params["page"])
        items = [{"id": f"s{i}"} for i in range(page * 2 - 1, page * 2 + 1)]
        return httpx.Response(200, json={"items": items, "total": 5})

    ids = client_for(handler).list_student_ids("t")
    assert ids[:4] == ["s1", "s2", "s3", "s4"] and len(ids) >= 5


def test_list_classes_maps_id_to_name():
    c = client_for(lambda r: httpx.Response(200, json={"items": [{"id": "c1", "name": "Grade 3"}], "total": 1}))
    assert c.list_classes("t") == {"c1": "Grade 3"}
