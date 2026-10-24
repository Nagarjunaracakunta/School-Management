from datetime import date

from tests.conftest import SEC_3A, SEC_4B

API = "/api/v1"
TODAY = date.today().isoformat()


def bulk(client, headers, section, records, day=TODAY):
    return client.post(
        f"{API}/attendance/bulk",
        json={
            "section_id": section,
            "date": day,
            "records": [{"student_id": s["id"], "status": st} for s, st in records],
        },
        headers=headers,
    )


def test_teacher_marks_a_whole_section(client, students, teacher1):
    students.add_teacher()
    a, b, c = (students.add_student(n) for n in ("Asha", "Bo", "Cy"))
    r = bulk(client, teacher1, SEC_3A, [(a, "PRESENT"), (b, "ABSENT"), (c, "LATE")])
    assert r.status_code == 200
    assert r.json() == {
        "date": TODAY,
        "section_id": SEC_3A,
        "created": 3,
        "updated": 0,
        "absent_notifications": 1,
    }
    assert client.get(f"{API}/attendance", headers=teacher1).json()["total"] == 3


def test_second_submission_corrects_instead_of_duplicating(client, students, teacher1, publisher):
    students.add_teacher()
    a, b = students.add_student("Asha"), students.add_student("Bo")
    bulk(client, teacher1, SEC_3A, [(a, "PRESENT"), (b, "ABSENT")])
    again = bulk(client, teacher1, SEC_3A, [(a, "ABSENT"), (b, "ABSENT")]).json()
    assert (again["created"], again["updated"], again["absent_notifications"]) == (0, 2, 1)  # only Asha is new
    assert client.get(f"{API}/attendance", headers=teacher1).json()["total"] == 2
    assert client.app.state.relay.publish_pending() == 2  # Bo once, Asha once


def test_student_outside_the_section_rejects_everything(client, students, teacher1):
    students.add_teacher()
    mine = students.add_student("Mine")
    stranger = students.add_student("Elsewhere", section=SEC_4B)
    r = bulk(client, teacher1, SEC_3A, [(mine, "ABSENT"), (stranger, "PRESENT")])
    assert r.status_code == 422 and r.json()["error"]["details"]["student_ids"] == [stranger["id"]]
    assert client.get(f"{API}/attendance", headers=teacher1).json()["total"] == 0  # all-or-nothing
    assert client.app.state.relay.publish_pending() == 0


def test_teacher_cannot_mark_a_section_they_do_not_teach(client, students, teacher1):
    students.add_teacher(sections=(SEC_3A,))
    other = students.add_student(section=SEC_4B)
    assert bulk(client, teacher1, SEC_4B, [(other, "PRESENT")]).status_code == 422


def test_admin_can_mark_any_section_and_parent_cannot(client, students, admin, parent1):
    s = students.add_student(section=SEC_4B)
    assert bulk(client, admin, SEC_4B, [(s, "PRESENT")]).status_code == 200
    assert bulk(client, parent1, SEC_4B, [(s, "PRESENT")]).status_code == 403


def test_bulk_applies_the_date_rules(client, students, admin, teacher1):
    students.add_teacher()
    s = students.add_student()
    assert bulk(client, teacher1, SEC_3A, [(s, "PRESENT")], day="2020-01-01").status_code == 403
    assert bulk(client, admin, SEC_3A, [(s, "PRESENT")], day="2999-01-01").status_code == 422
    assert bulk(client, admin, SEC_3A, [(s, "PRESENT"), (s, "ABSENT")]).status_code == 422
