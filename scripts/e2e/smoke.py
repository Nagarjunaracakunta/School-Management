#!/usr/bin/env python3
"""End-to-end smoke test: the three business flows, through the SAME address a browser uses.

    SMOKE_EMAIL=admin@school.example SMOKE_PASSWORD=... scripts/e2e/smoke.py http://localhost:8080          # local stack
    SMOKE_EMAIL=... SMOKE_PASSWORD=... scripts/e2e/smoke.py https://dxxxx.cloudfront.net                  # AWS (dev)

Flows (each is a numbered step in the output):
  1 Admission   parent applies -> admin approves -> enrolls -> student exists, linked to a class section
  2 Fee         admin assigns a fee -> payment -> receipt -> fee is PAID
  3 Attendance  teacher marks the student ABSENT -> history shows it
  4 Events      each of the above produced a notification (queue -> worker -> topic), checked by polling
  5 Security    no token = 401, a parent cannot create a class (403), the request id comes back

Creates a few records named "smoke-<random>". Run it against dev, not prod. Needs only the Python standard library.
"""

import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request
from datetime import date, timedelta

BASE = ""
failures: list[str] = []


def call(method, path, body=None, token=None, headers=None, expect=None):
    """One HTTP call. Returns (status, parsed JSON or None, response headers). Never raises on HTTP errors."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw, status, hdrs = resp.read(), resp.status, resp.headers
    except urllib.error.HTTPError as err:
        raw, status, hdrs = err.read(), err.code, err.headers
    try:
        parsed = json.loads(raw) if raw else None
    except ValueError:
        parsed = None
    if expect is not None and status != expect:
        raise AssertionError(f"{method} {path}: expected HTTP {expect}, got {status}: {raw[:300]!r}")
    return status, parsed, hdrs


def step(number, text):
    print(f"\n[{number}] {text}")


def ok(text):
    print(f"    ok  {text}")


def check(condition, text):
    if condition:
        ok(text)
    else:
        failures.append(text)
        print(f"  FAIL  {text}")


def login(email, password):
    _, body, _ = call("POST", "/api/v1/auth/login", {"email": email, "password": password}, expect=200)
    return body["access_token"]


def main() -> int:
    global BASE
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    BASE = sys.argv[1].rstrip("/")
    email, password = os.environ.get("SMOKE_EMAIL"), os.environ.get("SMOKE_PASSWORD")
    if not email or not password:
        sys.exit("set SMOKE_EMAIL and SMOKE_PASSWORD (an existing administrator)")
    tag = f"smoke-{secrets.token_hex(3)}"
    parent_email = f"{tag}@example.com"
    parent_password = secrets.token_urlsafe(18) + "Aa1!"
    started = time.time()

    step(0, "Is the platform reachable? (login page data, token verification keys)")
    status, jwks, _ = call("GET", "/.well-known/jwks.json")
    check(status == 200 and jwks and jwks.get("keys"), "public keys are published at /.well-known/jwks.json")
    admin = login(email, password)
    ok("administrator logged in")

    step(1, "ADMISSION: a parent applies, the administrator approves and enrolls")
    klass = call("POST", "/api/v1/classes", {"name": tag}, admin, expect=201)[1]
    section = call("POST", "/api/v1/sections", {"class_id": klass["id"], "name": "A", "capacity": 30}, admin, expect=201)[1]
    parent = call("POST", "/api/v1/users", {"email": parent_email, "full_name": f"Parent {tag}", "role": "parent",
                                           "password": parent_password}, admin, expect=201)[1]
    parent_token = login(parent_email, parent_password)
    ok("parent account created and logged in")
    dob = (date.today() - timedelta(days=365 * 8)).isoformat()
    admission = call("POST", "/api/v1/admissions", {
        "applicant_name": f"Student {tag}", "date_of_birth": dob, "class_applied": tag,
        "parents": [{"name": f"Parent {tag}", "email": parent_email, "phone": "+919876543210", "relationship": "MOTHER"}],
    }, parent_token, expect=201)[1]
    check(admission["status"] == "SUBMITTED", "admission is SUBMITTED")
    call("PUT", f"/api/v1/admissions/{admission['id']}", {"status": "APPROVED", "review_notes": "smoke test"}, admin, expect=200)
    enrolled = call("POST", f"/api/v1/admissions/{admission['id']}/enroll", None, admin, expect=200)[1]
    check(enrolled["status"] == "ENROLLED" and enrolled["student_id"], "admission is ENROLLED and a student record exists (admission -> student call)")
    student_id = enrolled["student_id"]
    call("POST", f"/api/v1/students/{student_id}/enrollments", {"section_id": section["id"]}, admin, expect=201)
    check(call("GET", f"/api/v1/students/{student_id}", token=admin, expect=200)[1]["name"] == f"Student {tag}", "student can be read back")

    step(2, "FEE: assign a fee, pay it, get a receipt")
    structure = call("POST", "/api/v1/fee-structures", {
        "name": f"Tuition {tag}", "class_id": klass["id"], "academic_year": "2026-27",
        "amount": "1000.00", "due_date": (date.today() + timedelta(days=30)).isoformat(),
    }, admin, expect=201)[1]
    fee = call("POST", "/api/v1/fees", {"student_id": student_id, "structure_id": structure["id"]}, admin, expect=201)[1]
    payment = call("POST", "/api/v1/payments", {"fee_id": fee["id"], "amount": "1000.00", "method": "UPI"}, parent_token,
                   headers={"Idempotency-Key": secrets.token_hex(8)}, expect=201)[1]
    check(bool(payment["receipt_no"]), f"payment accepted, receipt {payment['receipt_no']}")
    again = call("POST", "/api/v1/payments", {"fee_id": fee["id"], "amount": "1000.00", "method": "UPI"}, parent_token,
                 headers={"Idempotency-Key": secrets.token_hex(8)})[0]
    check(again in (409, 422), f"paying an already-paid fee is refused (HTTP {again})")
    fees = call("GET", f"/api/v1/students/{student_id}/fees", token=parent_token, expect=200)[1]
    check(fees["items"] and fees["items"][0]["status"] == "PAID", "the parent sees the fee as PAID (fee -> student call)")

    step(3, "ATTENDANCE: mark the student absent")
    call("POST", "/api/v1/attendance", {"subject_type": "student", "subject_id": student_id,
                                        "date": date.today().isoformat(), "status": "ABSENT"}, admin, expect=201)
    history = call("GET", f"/api/v1/students/{student_id}/attendance", token=admin, expect=200)[1]
    check(any(r["status"] == "ABSENT" for r in history["items"]), "attendance history shows ABSENT")

    step(4, "EVENTS: admission, payment and attendance each produced a notification (SQS -> worker -> SNS)")
    wanted, seen, deadline = 3, [], time.time() + 90
    while time.time() < deadline:
        page = call("GET", "/api/v1/notifications", token=admin, expect=200)[1]
        seen = [n for n in page["items"] if n["recipient"] == parent_email or tag in (n["message"] + n["subject"])]
        if len(seen) >= wanted:
            break
        time.sleep(3)
    kinds = sorted({n["event_type"] for n in seen})
    check(len(seen) >= wanted, f"{len(seen)} notifications for this parent/student after {int(time.time() - deadline + 90)}s: {kinds}")

    step(5, "SECURITY: authentication, authorization, request ids")
    check(call("GET", "/api/v1/students")[0] == 401, "no token = 401")
    check(call("POST", "/api/v1/classes", {"name": "nope"}, parent_token)[0] == 403, "a parent cannot create a class = 403")
    check(call("GET", "/api/v1/users", token=parent_token)[0] == 403, "a parent cannot list users = 403")
    rid = secrets.token_hex(8)
    echoed = call("GET", "/api/v1/auth/me", token=admin, headers={"X-Request-ID": rid}, expect=200)[2].get("X-Request-ID")
    check(echoed == rid, "the X-Request-ID we sent comes back (so logs can be correlated)")

    print(f"\n{'PASSED' if not failures else 'FAILED'} in {time.time() - started:.1f}s  ({BASE})")
    for f in failures:
        print("  -", f)
    return 1 if failures else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as err:
        print(f"\nFAILED: {err}")
        sys.exit(1)
