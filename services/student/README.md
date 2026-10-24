# Student (Academic) Service

Students, parents, classes, sections, subjects, teachers, teacher assignments and enrollments.
FastAPI + SQLAlchemy + PostgreSQL (schema `student`).

```bash
cd services/student
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
uvicorn app.asgi:app --reload --port 8003   # docs: http://localhost:8003/docs
pytest
```
