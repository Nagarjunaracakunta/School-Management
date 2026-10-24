import uuid
from datetime import date, timedelta

API = "/api/v1"
MISSING = str(uuid.uuid4())


def test_structure_rules(client, admin, auth, parent1, students):
    from tests.conftest import CLASS_ID

    body = {
        "name": "Tuition",
        "class_id": str(CLASS_ID),
        "academic_year": "2026-27",
        "amount": "15000",
        "due_date": "2026-07-10",
    }
    created = client.post(f"{API}/fee-structures", json=body, headers=admin)
    assert created.status_code == 201 and created.json()["class_name"] == "Grade 3"
    assert created.json()["amount"] == "15000.00"
    assert client.post(f"{API}/fee-structures", json=body, headers=admin).status_code == 409
    assert client.post(f"{API}/fee-structures", json={**body, "class_id": MISSING}, headers=admin).status_code == 404
    assert client.post(f"{API}/fee-structures", json=body, headers=parent1).status_code == 403
    assert client.post(f"{API}/fee-structures", json=body, headers=auth(role="teacher")).status_code == 403
    assert client.get(f"{API}/fee-structures", headers=admin).json()["total"] == 1
    assert client.get(f"{API}/fee-structures", headers=parent1).status_code == 403


def test_assign_fee_rules(client, admin, students, make_structure):
    student = students.add_student()
    structure = make_structure()
    body = {"student_id": student["id"], "structure_id": structure["id"]}

    ok = client.post(f"{API}/fees", json=body, headers=admin)
    assert ok.status_code == 201
    fee = ok.json()
    assert (fee["student_name"], fee["amount_due"], fee["outstanding"], fee["status"]) == (
        "Asha Rao",
        "15000.00",
        "15000.00",
        "PENDING",
    )
    assert client.post(f"{API}/fees", json=body, headers=admin).status_code == 409  # already assigned

    other = students.add_student(name="Bo")
    scholarship = client.post(
        f"{API}/fees",
        json={"student_id": other["id"], "structure_id": structure["id"], "amount": "9000"},
        headers=admin,
    )
    assert scholarship.json()["amount_due"] == "9000.00"

    inactive = students.add_student(name="Gone", status="INACTIVE")
    assert client.post(f"{API}/fees", json={**body, "student_id": inactive["id"]}, headers=admin).status_code == 409
    assert client.post(f"{API}/fees", json={**body, "student_id": MISSING}, headers=admin).status_code == 404
    assert client.post(f"{API}/fees", json={**body, "structure_id": MISSING}, headers=admin).status_code == 404


def test_parent_sees_only_own_childrens_fees(client, admin, parent1, parent2, students, make_fee):
    mine = make_fee(students.add_student("Mine", owner="parent-1"), name="Tuition")
    theirs = make_fee(students.add_student("Theirs", owner="parent-2"), name="Tuition 2")

    own = client.get(f"{API}/fees", headers=parent1).json()
    assert [f["id"] for f in own["items"]] == [mine["id"]]
    assert client.get(f"{API}/fees", headers=admin).json()["total"] == 2
    assert client.get(f"{API}/fees/{mine['id']}", headers=parent1).status_code == 200
    assert client.get(f"{API}/fees/{theirs['id']}", headers=parent1).status_code == 404
    # asking for another family's child by id shows nothing rather than an error
    assert client.get(f"{API}/fees", params={"student_id": theirs["student_id"]}, headers=parent1).json()["total"] == 0
    assert client.get(f"{API}/fees", headers=parent2).json()["total"] == 1


def test_parent_without_children_sees_nothing(client, auth, make_fee):
    make_fee()
    assert client.get(f"{API}/fees", headers=auth(sub="stranger", role="parent")).json()["total"] == 0


def test_student_fees_endpoint(client, parent1, parent2, students, make_fee):
    fee = make_fee(students.add_student("Mine", owner="parent-1"))
    url = f"{API}/students/{fee['student_id']}/fees"
    assert client.get(url, headers=parent1).json()["total"] == 1
    assert client.get(url, headers=parent2).status_code == 404  # not your child
    assert client.get(f"{API}/students/{MISSING}/fees", headers=parent1).status_code == 404


def test_status_filters_and_overdue(client, admin, students, make_fee, pay):
    pending = make_fee(students.add_student("A"), name="Future", days_until_due=30)
    overdue = make_fee(students.add_student("B"), name="Late", days_until_due=-5)
    paid = make_fee(students.add_student("C"), name="Done", days_until_due=10, amount="500")
    assert pay(admin, paid["id"], "500.00").status_code == 201

    def ids(**params):
        return {f["id"] for f in client.get(f"{API}/fees", params=params, headers=admin).json()["items"]}

    assert ids(status="PENDING") == {pending["id"]}
    assert ids(status="OVERDUE") == {overdue["id"]}
    assert ids(status="PAID") == {paid["id"]}
    assert ids(outstanding="true") == {pending["id"], overdue["id"]}
    late = client.get(f"{API}/fees/{overdue['id']}", headers=admin).json()
    assert late["status"] == "OVERDUE" and late["due_date"] == (date.today() - timedelta(days=5)).isoformat()
    assert client.get(f"{API}/fees", params={"status": "BOGUS"}, headers=admin).status_code == 422
    assert client.get(f"{API}/fees", params={"page_size": 1000}, headers=admin).status_code == 422


def test_teacher_and_anonymous_are_blocked(client, auth, make_fee):
    make_fee()
    assert client.get(f"{API}/fees", headers=auth(role="teacher")).status_code == 403
    assert client.get(f"{API}/fees").status_code == 401


def test_student_service_outage_is_a_502_not_a_500(client, parent1, students):
    students.down = True
    r = client.get(f"{API}/fees", headers=parent1)
    assert r.status_code == 502 and r.json()["error"]["code"] == "upstream_error"
    assert client.get("/health").status_code == 200


def test_probes(client, monkeypatch):
    assert client.get("/ready").status_code == 200

    def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(client.app.state.engine, "connect", boom)
    assert client.get("/ready").status_code == 503
