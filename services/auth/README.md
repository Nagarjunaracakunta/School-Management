# Auth Service

Logins, users and roles. Issues the RS256 JWTs every other service verifies. FastAPI + SQLAlchemy + Argon2id
(PostgreSQL schema `auth`). The only service that holds the private signing key.

```bash
cd services/auth
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
python ../../scripts/dev_jwt.py admin >/dev/null        # creates .dev-keys/ (a local signing key pair) if missing
cp .env.example .env
AUTH_ADMIN_PASSWORD='choose a long passphrase' python -m app.cli create-admin --email you@school.org --name "You"
uvicorn app.asgi:app --reload --port 8001               # docs: http://localhost:8001/docs
pytest
```

Then log in: `curl -X POST localhost:8001/api/v1/auth/login -H 'Content-Type: application/json' -d '{"email":"you@school.org","password":"..."}'`.
See [docs/security.md](../../docs/security.md) and [ADR 0003](../../docs/adr/0003-authentication-and-tokens.md).
