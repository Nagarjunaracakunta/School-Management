import json

import pytest

URL = "/api/v1/admissions"


def create(client, auth, payload, **who):
    return client.post(URL, json=payload, headers=auth(**who))


def test_parent_can_submit_admission(client, auth, valid_payload):
    r = create(client, auth, valid_payload, sub="parent-1", role="parent")
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "SUBMITTED"
    assert body["parents"][0]["email"] == "ravi@example.com"
    assert r.headers["Location"] == f"{URL}/{body['id']}"


def test_submit_without_token_is_401(client, valid_payload):
    r = client.post(URL, json=valid_payload)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"


def test_teacher_is_forbidden(client, auth, valid_payload):
    assert create(client, auth, valid_payload, role="teacher").status_code == 403


def test_validation_error_uses_standard_format(client, auth, valid_payload):
    valid_payload["parents"][0]["email"] = "not-an-email"
    r = create(client, auth, valid_payload, role="parent")
    assert r.status_code == 422
    error = r.json()["error"]
    assert error["code"] == "validation_error"
    assert error["request_id"] == r.headers["X-Request-ID"]
    assert any("email" in d["field"] for d in error["details"])


def test_request_id_is_echoed(client):
    r = client.get("/health", headers={"X-Request-ID": "my-trace-id-123"})
    assert r.headers["X-Request-ID"] == "my-trace-id-123"


def test_parent_sees_only_own_applications(client, auth, valid_payload):
    mine = create(client, auth, valid_payload, sub="p1", role="parent").json()
    create(client, auth, valid_payload, sub="p2", role="parent")

    listing = client.get(URL, headers=auth(sub="p1", role="parent")).json()
    assert listing["total"] == 1 and listing["items"][0]["id"] == mine["id"]
    assert client.get(URL, headers=auth(role="admin")).json()["total"] == 2


def test_other_parents_record_is_404_not_403(client, auth, valid_payload):
    created = create(client, auth, valid_payload, sub="p1", role="parent").json()
    r = client.get(f"{URL}/{created['id']}", headers=auth(sub="p2", role="parent"))
    assert r.status_code == 404


def test_unknown_and_malformed_ids(client, auth):
    h = auth()
    assert client.get(f"{URL}/00000000-0000-0000-0000-000000000000", headers=h).status_code == 404
    assert client.get(f"{URL}/not-a-uuid", headers=h).status_code == 422


def test_pagination_and_filters(client, auth, valid_payload):
    for i in range(5):
        valid_payload["applicant_name"] = f"Student {i}"
        valid_payload["class_applied"] = "Grade 1" if i < 3 else "Grade 2"
        create(client, auth, valid_payload)
    h = auth()
    page = client.get(URL, params={"page": 2, "page_size": 2}, headers=h).json()
    assert (page["total"], len(page["items"]), page["page"]) == (5, 2, 2)
    assert client.get(URL, params={"class_applied": "Grade 2"}, headers=h).json()["total"] == 2
    assert client.get(URL, params={"q": "student 3"}, headers=h).json()["total"] == 1
    assert client.get(URL, params={"q": "%"}, headers=h).json()["total"] == 0  # wildcard is escaped
    assert client.get(URL, params={"page_size": 1000}, headers=h).status_code == 422
    assert client.get(URL, params={"status": "BOGUS"}, headers=h).status_code == 422


def test_admin_review_flow_and_events(client, auth, valid_payload, publisher):
    created = create(client, auth, valid_payload, sub="p1", role="parent").json()
    r = client.put(f"{URL}/{created['id']}", json={"status": "APPROVED", "review_notes": "Welcome"}, headers=auth())
    assert r.status_code == 200
    assert r.json()["status"] == "APPROVED" and r.json()["review_notes"] == "Welcome"

    client.app.state.relay.publish_pending()
    types = [t for t, _ in publisher.sent]
    assert types == ["admission.submitted", "admission.approved"]


def test_invalid_transition_is_409(client, auth, valid_payload):
    created = create(client, auth, valid_payload).json()
    h = auth()
    client.put(f"{URL}/{created['id']}", json={"status": "REJECTED"}, headers=h)
    r = client.put(f"{URL}/{created['id']}", json={"status": "APPROVED"}, headers=h)
    assert r.status_code == 409 and r.json()["error"]["code"] == "conflict"


def test_enrolled_cannot_be_set_manually(client, auth, valid_payload):
    created = create(client, auth, valid_payload).json()
    r = client.put(f"{URL}/{created['id']}", json={"status": "ENROLLED"}, headers=auth())
    assert r.status_code == 409


def test_parent_cannot_review(client, auth, valid_payload):
    created = create(client, auth, valid_payload, sub="p1", role="parent").json()
    r = client.put(f"{URL}/{created['id']}", json={"status": "APPROVED"}, headers=auth(sub="p1", role="parent"))
    assert r.status_code == 403


def test_empty_update_is_422(client, auth, valid_payload):
    created = create(client, auth, valid_payload).json()
    assert client.put(f"{URL}/{created['id']}", json={}, headers=auth()).status_code == 422


@pytest.mark.parametrize("path", ["/health", "/ready"])
def test_probes_need_no_auth(client, path):
    assert client.get(path).status_code == 200


def test_ready_returns_503_when_database_is_down(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(client.app.state.engine, "connect", boom)
    assert client.get("/ready").status_code == 503
    assert client.get("/health").status_code == 200  # liveness unaffected


def test_unhandled_error_returns_500_with_request_id(client, auth, monkeypatch):
    from app.repositories.admission_repository import AdmissionRepository

    monkeypatch.setattr(AdmissionRepository, "search", lambda *a, **k: 1 / 0)
    r = client.get(URL, headers=auth())
    assert r.status_code == 500
    assert r.json()["error"]["request_id"] == r.headers["X-Request-ID"]
    assert "division" not in json.dumps(r.json())  # internals are not leaked
