import uuid
from datetime import date, timedelta

from tests.conftest import SEC_4B

API = "/api/v1"


def seed(students, mark, admin):
    """Asha (parent-1): P, L, A over 3 days. Bo (parent-2, other section): P today."""
    students.add_teacher()
    asha = students.add_student("Asha", owner="parent-1")
    bo = students.add_student("Bo", owner="parent-2", section=SEC_4B, class_name="Grade 4", section_name="B")
    mark(admin, asha, "PRESENT", 0)
    mark(admin, asha, "LATE", 1)
    mark(admin, asha, "ABSENT", 2)
    mark(admin, bo, "PRESENT", 0)
    return asha, bo


def test_listing_is_scoped_per_role(client, students, admin, teacher1, parent1, auth, mark):
    seed(students, mark, admin)
    assert client.get(f"{API}/attendance", headers=admin).json()["total"] == 4
    assert client.get(f"{API}/attendance", headers=teacher1).json()["total"] == 3  # only section 3A
    assert client.get(f"{API}/attendance", headers=parent1).json()["total"] == 3  # only their child
    nobody = auth(sub="stranger", role="parent")
    assert client.get(f"{API}/attendance", headers=nobody).json()["total"] == 0


def test_listing_filters_and_pagination(client, students, admin, mark):
    asha, _ = seed(students, mark, admin)
    teacher = next(iter(students.teachers.values()))
    mark(admin, teacher["id"], "PRESENT", subject_type="teacher")

    def total(**p):
        return client.get(f"{API}/attendance", params=p, headers=admin).json()["total"]

    assert total(subject_type="teacher") == 1 and total(subject_type="student") == 4
    assert total(status="ABSENT") == 1
    two_days_ago = (date.today() - timedelta(days=2)).isoformat()
    assert total(date_from=two_days_ago, date_to=two_days_ago) == 1
    page = client.get(f"{API}/attendance", params={"page": 2, "page_size": 2}, headers=admin).json()
    assert (page["total"], len(page["items"])) == (5, 2)
    assert client.get(f"{API}/attendance", params={"status": "SICK"}, headers=admin).status_code == 422
    assert client.get(f"{API}/attendance", params={"page_size": 500}, headers=admin).status_code == 422


def test_non_admins_never_see_teacher_attendance(client, students, admin, teacher1, mark):
    seed(students, mark, admin)
    teacher = next(iter(students.teachers.values()))
    mark(admin, teacher["id"], "ABSENT", subject_type="teacher")
    assert client.get(f"{API}/attendance", params={"subject_type": "teacher"}, headers=teacher1).json()["total"] == 0


def test_student_history_respects_ownership(client, students, admin, parent1, auth, mark):
    asha, bo = seed(students, mark, admin)
    mine = client.get(f"{API}/students/{asha['id']}/attendance", headers=parent1).json()
    assert [r["status"] for r in mine["items"]] == ["PRESENT", "LATE", "ABSENT"]  # newest first
    assert client.get(f"{API}/students/{bo['id']}/attendance", headers=parent1).status_code == 404
    assert client.get(f"{API}/students/{uuid.uuid4()}/attendance", headers=admin).status_code == 404
    since = (date.today() - timedelta(days=1)).isoformat()
    recent = client.get(f"{API}/students/{asha['id']}/attendance", params={"date_from": since}, headers=parent1)
    assert recent.json()["total"] == 2


def test_teacher_history_is_admin_or_self(client, students, admin, teacher1, parent1, auth, mark):
    me = students.add_teacher("Me", "teacher-1")
    other = students.add_teacher("Other", "teacher-2")
    mark(admin, me["id"], "PRESENT", subject_type="teacher")

    assert client.get(f"{API}/teachers/{me['id']}/attendance", headers=admin).json()["total"] == 1
    assert client.get(f"{API}/teachers/{me['id']}/attendance", headers=teacher1).json()["total"] == 1
    assert client.get(f"{API}/teachers/{other['id']}/attendance", headers=teacher1).status_code == 404
    assert client.get(f"{API}/teachers/{me['id']}/attendance", headers=parent1).status_code == 403
    assert client.get(f"{API}/teachers/{uuid.uuid4()}/attendance", headers=admin).status_code == 404


def test_summary_counts_late_as_present(client, students, admin, parent1, mark):
    seed(students, mark, admin)
    today = date.today().isoformat()
    assert client.get(f"{API}/attendance/summary", params={"date": today}, headers=admin).json() == {
        "date": today,
        "present": 2,
        "late": 0,
        "absent": 0,
        "total": 2,
    }
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    day = client.get(f"{API}/attendance/summary", params={"date": yesterday}, headers=parent1).json()
    assert (day["present"], day["late"], day["absent"], day["total"]) == (1, 1, 0, 1)
    empty = client.get(f"{API}/attendance/summary", params={"date": "2001-01-01"}, headers=admin).json()
    assert empty["total"] == 0
    assert client.get(f"{API}/attendance/summary", headers=admin).status_code == 422


def test_summary_is_scoped(client, students, admin, teacher1, auth, mark):
    seed(students, mark, admin)
    today = date.today().isoformat()
    assert client.get(f"{API}/attendance/summary", params={"date": today}, headers=teacher1).json()["total"] == 1
    stranger = auth(sub="x", role="parent")
    assert client.get(f"{API}/attendance/summary", params={"date": today}, headers=stranger).json()["total"] == 0


def test_student_report(client, students, admin, teacher1, parent1, mark):
    seed(students, mark, admin)
    params = {"date_from": (date.today() - timedelta(days=7)).isoformat(), "date_to": date.today().isoformat()}
    rows = client.get(f"{API}/attendance/reports/students", params=params, headers=admin).json()
    asha = next(r for r in rows["items"] if r["student_name"] == "Asha")
    assert (asha["present"], asha["late"], asha["absent"], asha["total_days"]) == (1, 1, 1, 3)
    assert asha["attendance_percentage"] == 66.7  # late counts as attending, absent does not
    assert rows["total"] == 2

    by_section = client.get(
        f"{API}/attendance/reports/students",
        params={**params, "class_name": "Grade 4", "section_name": "B"},
        headers=admin,
    ).json()
    assert [r["student_name"] for r in by_section["items"]] == ["Bo"]
    scoped = client.get(f"{API}/attendance/reports/students", params=params, headers=teacher1).json()
    assert [r["student_name"] for r in scoped["items"]] == ["Asha"]  # teacher sees their section only
    assert client.get(f"{API}/attendance/reports/students", params=params, headers=parent1).status_code == 403


def test_report_range_rules(client, admin):
    url = f"{API}/attendance/reports/students"
    backwards = client.get(url, params={"date_from": "2026-02-01", "date_to": "2026-01-01"}, headers=admin)
    assert backwards.status_code == 422 and backwards.json()["error"]["code"] == "invalid_request"
    assert (
        client.get(url, params={"date_from": "2020-01-01", "date_to": "2026-01-01"}, headers=admin).status_code == 422
    )
    assert client.get(url, params={"date_from": "2026-01-01"}, headers=admin).status_code == 422
