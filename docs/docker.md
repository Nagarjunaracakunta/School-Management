# Docker

## What gets built

| Image | Source | Runs as | Listens on | Command |
|---|---|---|---|---|
| `school/<service>` (auth, admission, student, fee, attendance, notification) | [docker/python-service.Dockerfile](../docker/python-service.Dockerfile), context `services/<service>` | uid 10001 (non-root) | 8000 | `uvicorn app.asgi:app` |
| the same `school/notification` image | same | uid 10001 | none | `python -m app.worker` (queue consumer) |
| the same `school/<service>` image | same | uid 10001 | none | `alembic upgrade head` (migrations Job) |
| `school/db-tools` | [docker/db-tools.Dockerfile](../docker/db-tools.Dockerfile), context `tools/db-bootstrap` | uid 10001 | none | `python bootstrap.py`: creates the database schemas and roles (Job in the `school-platform` chart) |
| `school/frontend` (local only) | [frontend/Dockerfile](../frontend/Dockerfile) | uid 101 (non-root) | 8080 | nginx: static files + routes `/api/v1/...` to the services |

## Build and test

```bash
# build one service (the build context is the service folder)
docker build -f docker/python-service.Dockerfile -t school/fee:dev services/fee

# run that service's tests on the production Python version (the build fails if a test fails)
docker build -f docker/python-service.Dockerfile --target test services/fee

# look at what was built
docker image ls school/fee
docker history school/fee:dev
docker run --rm school/fee:dev id                 # uid=10001(app) gid=10001(app)
docker run --rm school/fee:dev pip list           # no pytest, no ruff: dev tools are not in the image
docker run --rm --entrypoint ls school/fee:dev /app    # app  alembic.ini  migrations   (no tests)
```

## Run the whole platform

```bash
scripts/local-up.sh        # builds, starts, creates the first admin, prints the URL (http://localhost:8080)
scripts/local-up.sh down   # stop (data kept)
scripts/local-up.sh reset  # stop and delete the database
```

What it starts, in order: `postgres` → `db-bootstrap` (schemas and roles) → `migrate-<service>` (tables) → the services;
`moto` (a local AWS) → `aws-init` (queue, dead-letter queue, topic) → the services that publish events and the worker.
Every container is read-only, has no Linux capabilities and cannot gain privileges.

## How the pieces map to AWS

| Local (Compose) | AWS |
|---|---|
| nginx container: static files + path routing | CloudFront (static files from S3) + ALB / Ingress (routing) |
| `postgres` container | Amazon RDS |
| `moto` | SQS, SNS |
| `db-bootstrap`, `migrate-*`, `aws-init` | a Kubernetes Job (pre-sync hook), Terraform |
| `.dev-secrets/`, `.dev-keys/` | Secrets Manager |
| `docker compose` | Kubernetes (EKS) + Helm + Argo CD |

## Common problems

| Symptom | Cause | Fix |
|---|---|---|
| `required variable PG_ADMIN_PASSWORD is missing` | Compose was run without the secrets file | Use `scripts/local-up.sh`, or add `--env-file .dev-secrets/db.env` |
| A service is `unhealthy` | It cannot reach the database or has a bad setting | `docker compose ... logs <service>` (the logs are JSON, one object per line) |
| `migrate-<x>` exited with an error | Wrong migrator password, or the schema does not exist | Re-run `db-bootstrap`: `docker compose ... up db-bootstrap` |
| Login works but other pages return 401 | The services have a different public key than the one the Auth service signs with | Make sure `.dev-keys/` was not regenerated halfway; `reset` and start again |
| `permission denied` reading the private key in the Auth container | The key file permissions on the host | `chmod 644` the **local dev** key; real keys come from Secrets Manager |
| Docker itself reports `input/output error` | Your computer's disk is full | Free space, restart Docker Desktop |
