# ADR 0004: Container images

Status: Accepted
Date: 2026-10-24

| # | Decision | Reason | Revisit when |
|---|---|---|---|
| D29 | One shared `docker/python-service.Dockerfile` for all six Python services (build context = the service folder) | Six copies would drift apart. Services stay independently buildable and deployable | A service needs system libraries or a different base |
| D30 | Multi-stage build: `builder` (installs dependencies) → `test` (optional, runs pytest) → `runtime` (shipped) | The shipped image has no pip, compilers, tests or dev tools: smaller and less to attack. `--target test` runs a service's tests on the exact Python version that will run in production | Never expected |
| D31 | Base image `python:3.12-slim` (Debian). Not Alpine, not distroless, for now | Alpine uses musl, which breaks or slows prebuilt Python wheels (psycopg, cryptography, argon2). Distroless is smaller, but has no shell to debug with while we are learning | We have a mature pipeline: move to a pinned-by-digest distroless or Chainguard image |
| D32 | Run as a fixed non-root user (uid/gid 10001). Application files are owned by root and read-only to that user | A compromised process cannot rewrite its own code; Kubernetes can enforce `runAsNonRoot` because the numeric id is known | Never expected |
| D33 | The same image runs the API, the queue worker and the migrations Job; only the command differs (`uvicorn ...`, `python -m app.worker`, `alembic upgrade head`) | One artifact to build, scan, version and promote | A component needs a different dependency set |
| D34 | Containers are read-only with a memory-backed `/tmp`, no Linux capabilities, `no-new-privileges`. The application never writes outside `/tmp` | Limits what an attacker can do after a break-in. Docker Compose and Kubernetes (Phase 14) apply the same settings | Never expected |
| D35 | No secrets in images. Config comes from environment variables; keys and passwords are mounted or injected at run time. A `.dockerignore` keeps `.env`, `*.pem`, local databases and caches out of the build | Anyone who can pull an image can read every layer | Never expected |
| D36 | The frontend image (nginx) is for **local use only**. In AWS the frontend is static files in S3 behind CloudFront | See D1: no servers to run or patch for static files | Never expected |
| D37 | Tests run during the image build (`--target test` for the services, `npm test` in the frontend build) | A broken change cannot produce an image. CI (Phase 16) runs the same targets | Never expected |

## Tagging

Images are tagged with the **git commit SHA** (for example `fee:3f9c1ab`), never only `latest`. A tag identifies exactly
one build, which is what GitOps (Phase 19) needs: the Git repository says which SHA runs where, and a rollback is a revert.
In ECR, tags are made immutable so a tag can never be silently overwritten.
