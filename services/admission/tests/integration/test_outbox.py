import json

URL = "/api/v1/admissions"


def submit(client, auth, payload):
    return client.post(URL, json=payload, headers=auth(role="parent", sub="p1")).json()


def test_event_envelope_and_marking(client, auth, valid_payload, publisher):
    created = submit(client, auth, valid_payload)
    relay = client.app.state.relay

    assert relay.publish_pending() == 1
    event_type, body = publisher.sent[0]
    envelope = json.loads(body)
    assert event_type == "admission.submitted"
    assert envelope["event_id"] and envelope["version"] == 1 and envelope["source"] == "admission-service"
    assert envelope["data"]["application_id"] == created["id"]
    assert envelope["data"]["parents"][0]["email"] == "ravi@example.com"

    assert relay.publish_pending() == 0  # already published, not sent twice


def test_failed_publish_is_retried_later(client, auth, valid_payload, publisher):
    submit(client, auth, valid_payload)
    relay = client.app.state.relay

    publisher.fail = True
    assert relay.publish_pending() == 0  # SQS down: request itself already succeeded
    publisher.fail = False
    assert relay.publish_pending() == 1  # nothing lost
