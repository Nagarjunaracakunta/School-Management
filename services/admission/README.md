# Admission Service

Student applications and parent details. FastAPI + SQLAlchemy + PostgreSQL (schema `admission`).

```bash
cd services/admission
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env                    # SQLite + log-only events for local use
python ../../scripts/dev_jwt.py admin   # prints a token (local dev only)
uvicorn app.asgi:app --reload --port 8002
pytest                                  # tests + coverage
```

API docs (local): http://localhost:8002/docs. Probes: `/health` (liveness), `/ready` (readiness).
