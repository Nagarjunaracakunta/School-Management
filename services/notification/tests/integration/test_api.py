import uuid

API = "/api/v1/notifications"
EMAIL = {"channel": "EMAIL", "recipient": "Ravi@Example.com", "subject": "Fee reminder", "message": "Please pay."}


def deliver_events(processor, event, *types):
    for t in types:
        processor.handle(event(t))


def test_admin_sends_a_manual_email(client, admin, sender):
    r = client.post(API, json=EMAIL, headers=admin)
    assert r.status_code == 201
    body = r.json()
    assert (body["status"], body["attempts"], body["event_type"], body["recipient"]) == (
        "SENT",
        1,
        "manual",
        "ravi@example.com",
    )
    assert r.headers["Location"] == f"{API}/{body['id']}" and body["sent_at"]
    assert sender.sent == [("EMAIL", "ravi@example.com", "Fee reminder", "Please pay.")]


def test_manual_send_failure_is_visible_not_hidden(client, admin, sender):
    sender.fail = True
    r = client.post(API, json=EMAIL, headers=admin)
    assert r.status_code == 201 and r.json()["status"] == "FAILED" and r.json()["last_error"].startswith("RuntimeError")


def test_manual_sms(client, admin):
    r = client.post(API, json={"channel": "SMS", "recipient": "+91 98765 43210", "message": "Hi"}, headers=admin)
    assert r.status_code == 201 and r.json()["channel"] == "SMS" and r.json()["status"] == "SENT"


def test_only_admin_can_send_or_retry(client, admin, parent, auth):
    for headers in (parent, auth(role="teacher")):
        assert client.post(API, json=EMAIL, headers=headers).status_code == 403
        assert client.post(f"{API}/{uuid.uuid4()}/retry", headers=headers).status_code == 403
    assert client.post(API, json=EMAIL).status_code == 401


def test_validation_errors_use_the_standard_format(client, admin):
    r = client.post(API, json={"channel": "EMAIL", "recipient": "nope", "message": ""}, headers=admin)
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"
    assert r.json()["error"]["request_id"] == r.headers["X-Request-ID"]


def test_retry_a_failed_notification(client, admin, sender):
    sender.fail = True
    failed = client.post(API, json=EMAIL, headers=admin).json()
    sender.fail = False
    again = client.post(f"{API}/{failed['id']}/retry", headers=admin)
    assert again.status_code == 200 and again.json()["status"] == "SENT" and again.json()["last_error"] is None
    assert client.post(f"{API}/{failed['id']}/retry", headers=admin).status_code == 409  # already sent
    assert client.post(f"{API}/{uuid.uuid4()}/retry", headers=admin).status_code == 404


def test_retry_that_fails_again_stays_failed(client, admin, sender):
    sender.fail = True
    failed = client.post(API, json=EMAIL, headers=admin).json()
    again = client.post(f"{API}/{failed['id']}/retry", headers=admin).json()
    assert (again["status"], again["attempts"]) == ("FAILED", 1)


def test_parents_see_only_messages_addressed_to_them(client, admin, parent, auth, processor, event):
    deliver_events(processor, event, "payment.completed")  # 2 parents x (email + sms)
    assert client.get(API, headers=admin).json()["total"] == 4

    mine = client.get(API, headers=parent).json()  # ravi: his email AND his sms
    assert mine["total"] == 2 and {n["channel"] for n in mine["items"]} == {"EMAIL", "SMS"}
    assert all(n["recipient_name"] == "Ravi Rao" for n in mine["items"])

    stranger = auth(sub="x", role="parent", email="someone@else.com")
    assert client.get(API, headers=stranger).json()["total"] == 0
    no_email_claim = auth(sub="y", role="parent")
    assert client.get(API, headers=no_email_claim).json()["total"] == 0  # safe default
    assert client.get(API, headers=auth(role="teacher", sub="t")).json()["total"] == 0


def test_get_one_respects_ownership(client, admin, parent, processor, event, auth):
    deliver_events(processor, event, "attendance.absent")
    items = client.get(API, headers=admin).json()["items"]
    ravi = next(n for n in items if n["recipient_name"] == "Ravi Rao")
    sita = next(n for n in items if n["recipient_name"] == "Sita Rao")
    assert client.get(f"{API}/{ravi['id']}", headers=parent).status_code == 200
    assert client.get(f"{API}/{sita['id']}", headers=parent).status_code == 404  # someone else's
    assert client.get(f"{API}/{uuid.uuid4()}", headers=admin).status_code == 404
    assert client.get(f"{API}/not-a-uuid", headers=admin).status_code == 422


def test_internal_errors_are_hidden_from_parents(client, admin, parent, processor, event, sender):
    sender.fail = True
    body = event("admission.rejected")  # the SAME event delivered 3 times, as SQS would redeliver it
    for _ in range(3):
        processor.handle(body)
    admin_view = client.get(API, params={"status": "FAILED"}, headers=admin).json()["items"]
    assert admin_view and all("SNS unavailable" in n["last_error"] for n in admin_view)
    parent_view = client.get(API, headers=parent).json()["items"]
    assert parent_view and all(n["last_error"] is None for n in parent_view)


def test_filters_and_pagination(client, admin, processor, event):
    deliver_events(processor, event, "payment.completed", "attendance.absent", "admission.submitted")
    assert client.get(API, headers=admin).json()["total"] == 10

    def total(**params):
        return client.get(API, params=params, headers=admin).json()["total"]

    assert total(channel="SMS") == 4 and total(channel="EMAIL") == 6
    assert total(event_type="attendance.absent") == 4 and total(status="PENDING") == 0 and total(status="SENT") == 10
    page = client.get(API, params={"page": 2, "page_size": 4}, headers=admin).json()
    assert (page["total"], len(page["items"]), page["page"]) == (10, 4, 2)
    assert client.get(API, params={"status": "WEIRD"}, headers=admin).status_code == 422
    assert client.get(API, params={"page_size": 500}, headers=admin).status_code == 422


def test_probes(client, monkeypatch):
    assert client.get("/health").status_code == 200 and client.get("/ready").status_code == 200

    def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(client.app.state.engine, "connect", boom)
    assert client.get("/ready").status_code == 503
