import json
import uuid

from tests.conftest import SEC_4B

API = "/api/v1"


def test_teacher_marks_own_student_then_corrects(client, students, teacher1, mark):
    students.add_teacher()
    asha = students.add_student()
    first = mark(teacher1, asha, "PRESENT")
    assert first.status_code == 201
    body = first.json()
    assert (body["subject_name"], body["class_name"], body["section_name"], body["status"], body["marked_by"]) == (
        "Asha Rao",
        "Grade 3",
        "A",
        "PRESENT",
        "teacher-1",
    )

    fix = mark(teacher1, asha, "LATE")
    assert fix.status_code == 200 and fix.json()["id"] == body["id"] and fix.json()["status"] == "LATE"
    history = client.get(f"{API}/students/{asha['id']}/attendance", headers=teacher1).json()
    assert history["total"] == 1  # one row per day, never duplicates


def test_cannot_mark_students_of_a_section_you_do_not_teach(students, teacher1, mark):
    students.add_teacher()
    other = students.add_student(section=SEC_4B)
    assert mark(teacher1, other).status_code == 404


def test_parent_and_anonymous_cannot_mark(client, students, parent1, mark):
    asha = students.add_student()
    assert mark(parent1, asha).status_code == 403
    assert client.post(f"{API}/attendance", json={}).status_code == 401


def test_date_rules(client, students, admin, teacher1, mark):
    students.add_teacher()
    asha = students.add_student()
    future = mark(admin, asha, days_ago=-1)
    assert future.status_code == 422 and future.json()["error"]["code"] == "invalid_request"

    assert mark(teacher1, asha, days_ago=7).status_code == 201  # last day inside the window
    late = mark(teacher1, asha, days_ago=8)
    assert late.status_code == 403 and "ask an admin" in late.json()["error"]["message"]
    assert mark(admin, asha, days_ago=30).status_code == 201  # admins have no limit


def test_inactive_students_cannot_be_marked(students, admin, mark):
    gone = students.add_student(status="INACTIVE")
    assert mark(admin, gone).status_code == 409


def test_validation_errors_use_the_standard_format(client, students, admin):
    r = client.post(f"{API}/attendance", json={"subject_id": "nope", "date": "x", "status": "SICK"}, headers=admin)
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"
    fields = {d["field"] for d in r.json()["error"]["details"]}
    assert {"subject_id", "date", "status"} <= fields


def test_only_admin_marks_teacher_attendance(client, students, admin, teacher1, mark):
    teacher = students.add_teacher()
    ok = mark(admin, teacher["id"], "PRESENT", subject_type="teacher")
    assert ok.status_code == 201 and ok.json()["subject_name"] == "Mr T" and ok.json()["class_name"] is None
    assert mark(teacher1, teacher["id"], "PRESENT", subject_type="teacher").status_code == 403
    assert mark(admin, str(uuid.uuid4()), "PRESENT", subject_type="teacher").status_code == 404


def test_absence_event_goes_to_parents_once_per_change(client, students, admin, mark, publisher):
    asha = students.add_student()
    relay = client.app.state.relay

    mark(admin, asha, "ABSENT")
    mark(admin, asha, "ABSENT")  # re-saving the same status: no second message
    assert relay.publish_pending() == 1
    event_type, body = publisher.sent[0]
    envelope = json.loads(body)
    assert event_type == "attendance.absent" and envelope["source"] == "attendance-service"
    data = envelope["data"]
    assert (data["student_name"], data["section_name"]) == ("Asha Rao", "A")
    assert data["parents"][0]["email"] == "ravi@example.com"

    mark(admin, asha, "PRESENT")  # corrected: no event
    mark(admin, asha, "LATE")
    assert relay.publish_pending() == 0
    mark(admin, asha, "ABSENT")  # becomes absent again: notified again
    assert relay.publish_pending() == 1


def test_no_event_for_present_late_or_teacher_absence(client, students, admin, mark):
    asha, teacher = students.add_student(), students.add_teacher()
    mark(admin, asha, "PRESENT")
    mark(admin, asha, "LATE", days_ago=1)
    mark(admin, teacher["id"], "ABSENT", subject_type="teacher")
    assert client.app.state.relay.publish_pending() == 0


def test_publish_failure_never_loses_or_blocks_attendance(client, students, admin, mark, publisher):
    asha = students.add_student()
    publisher.fail = True
    assert mark(admin, asha, "ABSENT").status_code == 201
    assert client.app.state.relay.publish_pending() == 0
    publisher.fail = False
    assert client.app.state.relay.publish_pending() == 1


def test_student_service_outage_is_a_502_and_saves_nothing(client, students, admin, mark):
    asha = students.add_student()
    students.down = True
    assert mark(admin, asha).status_code == 502
    students.down = False
    assert client.get(f"{API}/attendance", headers=admin).json()["total"] == 0


def test_probes(client, monkeypatch):
    assert client.get("/health").status_code == 200 and client.get("/ready").status_code == 200

    def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(client.app.state.engine, "connect", boom)
    assert client.get("/ready").status_code == 503
