# Fee Service

Fee structures, fees owed per student, payments, receipts. FastAPI + SQLAlchemy + PostgreSQL (schema `fee`).
Publishes `payment.completed` to SQS via a transactional outbox. Asks the Student Service who may see which child.

```bash
cd services/fee
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
uvicorn app.asgi:app --reload --port 8004   # docs: http://localhost:8004/docs  (needs the Student Service on :8003)
pytest
```
