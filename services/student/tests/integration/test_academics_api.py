API = "/api/v1"
MISSING = "00000000-0000-0000-0000-000000000000"


def test_classes_and_sections(client, admin, auth):
    assert client.post(f"{API}/classes", json={"name": "Grade 1"}, headers=admin).status_code == 201
    dup = client.post(f"{API}/classes", json={"name": "Grade 1"}, headers=admin)
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "conflict"
    cls = client.get(f"{API}/classes", headers=auth(role="parent")).json()["items"][0]

    sec = client.post(f"{API}/sections", json={"class_id": cls["id"], "name": "A"}, headers=admin)
    assert sec.status_code == 201 and sec.json()["class_name"] == "Grade 1" and sec.json()["capacity"] == 40
    assert client.post(f"{API}/sections", json={"class_id": cls["id"], "name": "A"}, headers=admin).status_code == 409
    assert client.post(f"{API}/sections", json={"class_id": MISSING, "name": "A"}, headers=admin).status_code == 404
    assert (
        client.post(
            f"{API}/sections", json={"class_id": cls["id"], "name": "B", "capacity": 0}, headers=admin
        ).status_code
        == 422
    )

    listed = client.get(f"{API}/sections", params={"class_id": cls["id"]}, headers=auth(role="teacher")).json()
    assert listed["total"] == 1
    assert client.get(f"{API}/sections", params={"class_id": MISSING}, headers=admin).json()["total"] == 0


def test_only_admin_writes_reference_data(client, auth):
    for role in ("teacher", "parent"):
        h = auth(role=role)
        assert client.post(f"{API}/classes", json={"name": "X"}, headers=h).status_code == 403
        assert client.post(f"{API}/subjects", json={"name": "X", "code": "XX"}, headers=h).status_code == 403
        assert client.post(f"{API}/teachers", json={"name": "T"}, headers=h).status_code in (403, 422)


def test_subjects_and_teachers_enforce_uniqueness(client, admin):
    assert (
        client.post(f"{API}/subjects", json={"name": "Maths", "code": "math"}, headers=admin).json()["code"] == "MATH"
    )
    assert client.post(f"{API}/subjects", json={"name": "Maths", "code": "M2"}, headers=admin).status_code == 409
    teacher = {"name": "Mr T", "email": "T@School.org", "phone": "+91 91111 11111"}
    assert client.post(f"{API}/teachers", json=teacher, headers=admin).json()["email"] == "t@school.org"
    assert client.post(f"{API}/teachers", json=teacher, headers=admin).status_code == 409
    assert client.post(f"{API}/teachers", json={**teacher, "phone": "abc"}, headers=admin).status_code == 422


def test_teacher_assignments(client, admin, auth, make_section):
    section = make_section()
    subject = client.post(f"{API}/subjects", json={"name": "Maths", "code": "MATH"}, headers=admin).json()
    teacher = client.post(
        f"{API}/teachers", json={"name": "Mr T", "email": "t@s.org", "phone": "+91 91111 11111"}, headers=admin
    ).json()
    url = f"{API}/sections/{section['id']}/assignments"
    body = {"subject_id": subject["id"], "teacher_id": teacher["id"]}

    created = client.post(url, json=body, headers=admin)
    assert created.status_code == 201
    assert (created.json()["subject_name"], created.json()["teacher_name"]) == ("Maths", "Mr T")
    assert client.post(url, json=body, headers=admin).status_code == 409
    assert client.post(url, json={**body, "teacher_id": MISSING}, headers=admin).status_code == 404
    assert client.post(f"{API}/sections/{MISSING}/assignments", json=body, headers=admin).status_code == 404

    assert len(client.get(url, headers=auth(role="teacher")).json()) == 1
    assert client.get(url, headers=auth(role="parent")).status_code == 403
    assert client.get(f"{API}/teachers", headers=auth(role="parent")).status_code == 403
    assert client.get(f"{API}/teachers", headers=auth(role="teacher")).json()["total"] == 1


def test_probes_and_failure_modes(client, monkeypatch):
    assert client.get("/health").status_code == 200 and client.get("/ready").status_code == 200

    def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(client.app.state.engine, "connect", boom)
    assert client.get("/ready").status_code == 503
    assert client.get("/health").status_code == 200
