# Attendance Service

Daily attendance for students (and teachers), history, summaries and reports. FastAPI + SQLAlchemy + PostgreSQL
(schema `attendance`). Publishes `attendance.absent` to SQS via a transactional outbox. Asks the Student Service
who may see which student, so teachers can only mark their own sections.

```bash
cd services/attendance
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
uvicorn app.asgi:app --reload --port 8005   # docs: http://localhost:8005/docs  (needs the Student Service on :8003)
pytest
```
