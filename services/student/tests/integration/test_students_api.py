S = "/api/v1/students"


def test_admin_creates_student(client, admin, student_payload):
    r = client.post(S, json=student_payload, headers=admin)
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "Asha Rao" and body["status"] == "ACTIVE"
    assert body["class_name"] is None and body["parents"][0]["email"] == "ravi@example.com"
    assert r.headers["Location"] == f"{S}/{body['id']}"


def test_only_admin_creates(client, auth, student_payload):
    for role in ("parent", "teacher"):
        assert client.post(S, json=student_payload, headers=auth(role=role)).status_code == 403
    assert client.post(S, json=student_payload).status_code == 401


def test_same_admission_is_idempotent(client, admin, student_payload):
    ref = "11111111-1111-1111-1111-111111111111"
    first = client.post(S, json={**student_payload, "admission_ref": ref}, headers=admin)
    second = client.post(S, json={**student_payload, "admission_ref": ref}, headers=admin)
    assert (first.status_code, second.status_code) == (201, 200)
    assert first.json()["id"] == second.json()["id"]
    assert client.get(S, headers=admin).json()["total"] == 1


def test_siblings_share_one_parent(client, make_student):
    a = make_student(name="Asha Rao")
    b = make_student(name="Arun Rao")
    assert a["parents"][0]["id"] == b["parents"][0]["id"]


def test_parent_sees_only_own_children(client, auth, make_student):
    mine = make_student(name="Asha Rao", guardian_user_id="parent-1")
    other = make_student(
        name="Zed Other",
        guardian_user_id="parent-2",
        parents=[{"name": "Z", "email": "z@example.com", "phone": "+91 90000 00000"}],
    )
    mine_view = client.get(S, headers=auth(sub="parent-1", role="parent")).json()
    assert [s["id"] for s in mine_view["items"]] == [mine["id"]]
    assert client.get(f"{S}/{mine['id']}", headers=auth(sub="parent-1", role="parent")).status_code == 200
    assert client.get(f"{S}/{other['id']}", headers=auth(sub="parent-1", role="parent")).status_code == 404


def test_teacher_sees_only_students_in_their_sections(client, admin, auth, make_student, make_section):
    section = make_section()
    other_section = make_section(section="B")
    subject = client.post("/api/v1/subjects", json={"name": "Maths", "code": "MATH"}, headers=admin).json()
    teacher = client.post(
        "/api/v1/teachers",
        json={"name": "Mr T", "email": "t@school.org", "phone": "+91 91111 11111", "user_id": "teacher-1"},
        headers=admin,
    ).json()
    client.post(
        f"/api/v1/sections/{section['id']}/assignments",
        json={"subject_id": subject["id"], "teacher_id": teacher["id"]},
        headers=admin,
    )
    inside = make_student(name="Inside")
    outside = make_student(name="Outside", parents=[{"name": "P", "email": "p@e.com", "phone": "+91 92222 22222"}])
    client.post(f"{S}/{inside['id']}/enrollments", json={"section_id": section["id"]}, headers=admin)
    client.post(f"{S}/{outside['id']}/enrollments", json={"section_id": other_section["id"]}, headers=admin)

    t1 = auth(sub="teacher-1", role="teacher")
    assert [s["name"] for s in client.get(S, headers=t1).json()["items"]] == ["Inside"]
    assert client.get(f"{S}/{outside['id']}", headers=t1).status_code == 404
    assert client.get(S, headers=auth(sub="teacher-2", role="teacher")).json()["total"] == 0


def test_list_shows_current_class_and_section_and_filters(client, admin, make_student, make_section):
    s3a, s3b = make_section("Grade 3", "A"), make_section("Grade 3", "B")
    g4 = make_section("Grade 4", "A")
    names = {}
    for name, section in [("Anil", s3a), ("Bina", s3b), ("Chitra", g4)]:
        student = make_student(
            name=name, parents=[{"name": name, "email": f"{name}@e.com", "phone": "+91 93333 33333"}]
        )
        names[name] = student
        client.post(f"{S}/{student['id']}/enrollments", json={"section_id": section["id"]}, headers=admin)
    make_student(name="Unplaced", parents=[{"name": "U", "email": "u@e.com", "phone": "+91 94444 44444"}])

    everyone = client.get(S, headers=admin).json()
    assert everyone["total"] == 4
    anil = next(s for s in everyone["items"] if s["name"] == "Anil")
    assert (anil["class_name"], anil["section_name"]) == ("Grade 3", "A")

    assert client.get(S, params={"class_id": s3a["class_id"]}, headers=admin).json()["total"] == 2
    assert client.get(S, params={"section_id": g4["id"]}, headers=admin).json()["total"] == 1
    assert client.get(S, params={"q": "bin"}, headers=admin).json()["total"] == 1
    assert client.get(S, params={"q": "%"}, headers=admin).json()["total"] == 0
    page = client.get(S, params={"page": 2, "page_size": 3}, headers=admin).json()
    assert (page["total"], len(page["items"])) == (4, 1)
    assert client.get(S, params={"status": "BOGUS"}, headers=admin).status_code == 422


def test_update_student(client, admin, make_student):
    student = make_student()
    r = client.put(f"{S}/{student['id']}", json={"name": "Asha R", "status": "INACTIVE"}, headers=admin)
    assert r.status_code == 200 and (r.json()["name"], r.json()["status"]) == ("Asha R", "INACTIVE")
    assert client.get(S, params={"status": "ACTIVE"}, headers=admin).json()["total"] == 0
    missing = "00000000-0000-0000-0000-000000000000"
    assert client.put(f"{S}/{missing}", json={"name": "x"}, headers=admin).status_code == 404


def test_validation_error_format(client, admin, student_payload):
    student_payload["parents"][0]["email"] = "nope"
    r = client.post(S, json=student_payload, headers=admin)
    assert r.status_code == 422 and r.json()["error"]["request_id"] == r.headers["X-Request-ID"]
    assert client.get(f"{S}/not-a-uuid", headers=admin).status_code == 422


def test_enrollment_rules(client, admin, make_student, make_section):
    section = make_section(capacity=1)
    first = make_student(name="First")
    second = make_student(name="Second", parents=[{"name": "S", "email": "s@e.com", "phone": "+91 95555 55555"}])
    url = f"{S}/{first['id']}/enrollments"

    ok = client.post(url, json={"section_id": section["id"]}, headers=admin)
    assert ok.status_code == 201 and ok.json()["academic_year"] == "2026-27"
    assert client.post(url, json={"section_id": section["id"]}, headers=admin).status_code == 409  # twice in a year
    full = client.post(f"{S}/{second['id']}/enrollments", json={"section_id": section["id"]}, headers=admin)
    assert full.status_code == 409 and "full" in full.json()["error"]["message"]
    # next year is a different enrollment
    assert (
        client.post(url, json={"section_id": section["id"], "academic_year": "2027-28"}, headers=admin).status_code
        == 201
    )

    missing = "00000000-0000-0000-0000-000000000000"
    assert client.post(url, json={"section_id": missing}, headers=admin).status_code == 404
    assert (
        client.post(f"{S}/{missing}/enrollments", json={"section_id": section["id"]}, headers=admin).status_code == 404
    )
    assert (
        client.post(url, json={"section_id": section["id"], "academic_year": "bad"}, headers=admin).status_code == 422
    )

    history = client.get(url, headers=admin).json()
    assert [e["academic_year"] for e in history] == ["2027-28", "2026-27"]


def test_parent_can_view_own_childs_enrollments_only(client, admin, auth, make_student, make_section):
    section = make_section()
    child = make_student(guardian_user_id="parent-1")
    client.post(f"{S}/{child['id']}/enrollments", json={"section_id": section["id"]}, headers=admin)
    url = f"{S}/{child['id']}/enrollments"
    assert client.get(url, headers=auth(sub="parent-1", role="parent")).status_code == 200
    assert client.get(url, headers=auth(sub="parent-9", role="parent")).status_code == 404
    assert (
        client.post(url, json={"section_id": section["id"]}, headers=auth(sub="parent-1", role="parent")).status_code
        == 403
    )
