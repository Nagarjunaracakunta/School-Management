import json
import uuid

API = "/api/v1"
PAY = f"{API}/payments"
MISSING = str(uuid.uuid4())


def fee_of(client, headers, fee_id):
    return client.get(f"{API}/fees/{fee_id}", headers=headers).json()


def test_partial_then_full_payment(client, admin, parent1, make_fee, pay):
    fee = make_fee(amount="1000")
    first = pay(parent1, fee["id"], "400.00", "CARD")
    assert first.status_code == 201
    body = first.json()
    assert body["balance_after"] == "600.00" and body["status"] == "COMPLETED" and body["receipt_no"].startswith("RCT-")
    assert first.headers["Location"] == f"{PAY}/{body['id']}"
    assert (fee_of(client, admin, fee["id"])["status"], fee_of(client, admin, fee["id"])["outstanding"]) == (
        "PARTIAL",
        "600.00",
    )

    assert pay(parent1, fee["id"], "600.00").status_code == 201
    done = fee_of(client, admin, fee["id"])
    assert (done["status"], done["outstanding"], done["amount_paid"]) == ("PAID", "0.00", "1000.00")
    again = pay(parent1, fee["id"], "1.00")
    assert again.status_code == 409 and "fully paid" in again.json()["error"]["message"]


def test_cannot_overpay(client, parent1, make_fee, pay):
    fee = make_fee(amount="1000")
    r = pay(parent1, fee["id"], "1000.01")
    assert r.status_code == 409 and "outstanding" in r.json()["error"]["message"]
    assert client.get(PAY, headers=parent1).json()["total"] == 0


def test_same_key_is_not_charged_twice(client, admin, parent1, make_fee, pay):
    fee = make_fee(amount="1000")
    first = pay(parent1, fee["id"], "300.00", key="retry-key-0001")
    replay = pay(parent1, fee["id"], "300.00", key="retry-key-0001")

    assert (first.status_code, replay.status_code) == (201, 200)
    assert replay.headers["Idempotent-Replayed"] == "true" and replay.json()["id"] == first.json()["id"]
    assert fee_of(client, admin, fee["id"])["amount_paid"] == "300.00"  # charged once
    assert client.get(PAY, headers=admin).json()["total"] == 1


def test_key_reuse_for_a_different_request_is_rejected(client, parent1, parent2, make_fee, pay, students):
    fee = make_fee(amount="1000")
    assert pay(parent1, fee["id"], "300.00", key="shared-key-001").status_code == 201
    assert pay(parent1, fee["id"], "301.00", key="shared-key-001").status_code == 409  # different amount
    assert pay(parent1, fee["id"], "300.00", "CARD", key="shared-key-001").status_code == 409  # different method
    # another user cannot read or replay someone else's payment through the key
    assert pay(parent2, fee["id"], "300.00", key="shared-key-001").status_code == 409


def test_lost_race_on_the_same_key_returns_the_winner(client, parent1, make_fee, pay, monkeypatch):
    from app.services.payment_service import PaymentService

    fee = make_fee(amount="1000")
    first = pay(parent1, fee["id"], "300.00", key="race-key-0001")

    original = PaymentService._replay
    calls = {"n": 0}

    def blind_first_time(self, data, key, user):
        calls["n"] += 1
        return None if calls["n"] == 1 else original(self, data, key, user)

    monkeypatch.setattr(PaymentService, "_replay", blind_first_time)
    second = pay(parent1, fee["id"], "300.00", key="race-key-0001")  # the unique constraint catches it
    assert second.status_code == 200 and second.json()["id"] == first.json()["id"]


def test_idempotency_key_is_required_and_validated(client, parent1, make_fee):
    fee = make_fee()
    body = {"fee_id": fee["id"], "amount": "10", "method": "UPI"}
    missing = client.post(PAY, json=body, headers=parent1)
    assert missing.status_code == 422 and "Idempotency-Key" in json.dumps(missing.json())
    assert client.post(PAY, json=body, headers={**parent1, "Idempotency-Key": "short"}).status_code == 422
    assert (
        client.post(PAY, json=body, headers={**parent1, "Idempotency-Key": "bad key with spaces!"}).status_code == 422
    )


def test_invalid_payment_bodies(client, parent1, make_fee, pay):
    fee = make_fee()
    assert pay(parent1, fee["id"], "0").status_code == 422
    assert pay(parent1, fee["id"], "10.555").status_code == 422
    assert pay(parent1, fee["id"], "10", "BITCOIN").status_code == 422
    assert pay(parent1, MISSING, "10").status_code == 404


def test_cannot_pay_someone_elses_fee(client, parent2, parent1, make_fee, students, pay):
    fee = make_fee(students.add_student(owner="parent-1"))
    stolen = pay(parent2, fee["id"], "10")
    assert stolen.status_code == 404 and stolen.json()["error"]["message"] == "Fee not found"
    assert pay(parent1, fee["id"], "10").status_code == 201


def test_admin_can_record_a_cash_payment_and_teacher_cannot_pay(client, admin, auth, make_fee, pay):
    fee = make_fee()
    assert pay(admin, fee["id"], "50", "CASH").status_code == 201
    assert pay(auth(role="teacher"), fee["id"], "50").status_code == 403


def test_payment_event_carries_what_notification_needs(client, parent1, make_fee, pay, publisher):
    fee = make_fee(amount="1000")
    payment = pay(parent1, fee["id"], "250.00").json()

    assert client.app.state.relay.publish_pending() == 1
    event_type, body = publisher.sent[0]
    envelope = json.loads(body)
    assert event_type == "payment.completed" and envelope["source"] == "fee-service" and envelope["event_id"]
    data = envelope["data"]
    assert (data["payment_id"], data["amount"], data["balance_after"]) == (payment["id"], "250.00", "750.00")
    assert data["parents"][0]["email"] == "ravi@example.com" and data["student_name"] == "Asha Rao"
    assert client.app.state.relay.publish_pending() == 0


def test_rejected_payment_creates_no_event(client, parent1, make_fee, pay, publisher):
    fee = make_fee(amount="100")
    pay(parent1, fee["id"], "999")
    assert client.app.state.relay.publish_pending() == 0


def test_failed_publish_does_not_fail_or_lose_the_payment(client, parent1, make_fee, pay, publisher):
    fee = make_fee(amount="100")
    publisher.fail = True
    assert pay(parent1, fee["id"], "10").status_code == 201
    assert client.app.state.relay.publish_pending() == 0
    publisher.fail = False
    assert client.app.state.relay.publish_pending() == 1


def test_get_payment_and_receipt_respect_ownership(client, admin, parent1, parent2, make_fee, pay):
    fee = make_fee(amount="1000")
    payment = pay(parent1, fee["id"], "250.00", "UPI").json()
    url = f"{PAY}/{payment['id']}"

    assert client.get(url, headers=parent1).json()["id"] == payment["id"]
    receipt = client.get(f"{url}/receipt", headers=parent1).json()
    assert receipt["receipt_no"] == payment["receipt_no"] and receipt["balance_after"] == "750.00"
    assert (receipt["student_name"], receipt["fee_name"], receipt["payment_method"]) == (
        "Asha Rao",
        "Tuition Term 1",
        "UPI",
    )
    assert client.get(url, headers=admin).status_code == 200
    assert client.get(url, headers=parent2).status_code == 404
    assert client.get(f"{url}/receipt", headers=parent2).status_code == 404
    assert client.get(f"{PAY}/{MISSING}", headers=admin).status_code == 404


def test_payment_listing_is_scoped_and_filterable(client, admin, parent1, parent2, students, make_fee, pay):
    mine = make_fee(students.add_student("Mine", owner="parent-1"), name="A", amount="100")
    theirs = make_fee(students.add_student("Theirs", owner="parent-2"), name="B", amount="100")
    pay(parent1, mine["id"], "10")
    pay(parent1, mine["id"], "20")
    pay(parent2, theirs["id"], "30")

    assert client.get(PAY, headers=parent1).json()["total"] == 2
    assert client.get(PAY, headers=admin).json()["total"] == 3
    assert client.get(PAY, params={"fee_id": mine["id"]}, headers=admin).json()["total"] == 2
    assert client.get(PAY, params={"fee_id": theirs["id"]}, headers=parent1).json()["total"] == 0
    assert client.get(PAY, params={"status": "COMPLETED", "page_size": 1}, headers=admin).json()["items"].__len__() == 1
    assert client.get(PAY, params={"status": "WEIRD"}, headers=admin).status_code == 422
    assert client.get(PAY, headers=parent2).json()["items"][0]["amount"] == "30.00"


def test_student_service_outage_blocks_payment_safely(client, parent1, make_fee, pay, students):
    fee = make_fee(amount="100")
    students.down = True
    assert pay(parent1, fee["id"], "10", key="outage-key-001").status_code == 502
    students.down = False
    assert client.get(f"{API}/fees/{fee['id']}", headers=parent1).json()["amount_paid"] == "0.00"
    assert pay(parent1, fee["id"], "10", key="outage-key-001").status_code == 201  # same key, now works


def test_event_amounts_use_the_same_two_decimal_format_as_the_api(client, parent1, make_fee, publisher):
    fee = make_fee(amount="1000")
    client.post(
        PAY,
        json={"fee_id": fee["id"], "amount": 250, "method": "UPI"},  # whole number sent as a JSON number
        headers={**parent1, "Idempotency-Key": "format-key-001"},
    )
    client.app.state.relay.publish_pending()
    data = json.loads(publisher.sent[0][1])["data"]
    assert (data["amount"], data["balance_after"]) == ("250.00", "750.00")
