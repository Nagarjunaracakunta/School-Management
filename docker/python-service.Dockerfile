# syntax=docker/dockerfile:1
# One Dockerfile for all six Python services. The build context is the service's own folder:
#
#   docker build -f docker/python-service.Dockerfile -t school/fee:dev services/fee
#   docker build -f docker/python-service.Dockerfile --target test services/fee     # run its tests on this Python
#
# Stages: builder (install dependencies) -> test (optional, runs pytest) -> runtime (what is shipped).
ARG PYTHON_VERSION=3.12

# ---------------------------------------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS base
# No .pyc files (smaller, and the filesystem can be read-only), unbuffered logs (they reach the log driver at once),
# no pip cache or version nag inside the image.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# ---------------------------------------------------------------------------------------------------------
FROM base AS builder
# A virtualenv in one folder: the runtime stage copies just that folder, leaving pip and build leftovers behind.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"
WORKDIR /build
# Copy ONLY the requirements first. This layer is rebuilt only when dependencies change, not on every code edit.
COPY requirements.txt .
RUN pip install -r requirements.txt

# ---------------------------------------------------------------------------------------------------------
FROM builder AS test
COPY requirements-dev.txt .
RUN pip install -r requirements-dev.txt
WORKDIR /src
COPY . .
# Failing tests fail the build. Uses the default in-memory SQLite, so no database is needed here.
RUN pytest -q -p no:cacheprovider --no-cov

# ---------------------------------------------------------------------------------------------------------
# Last stage = the default target = what `docker build` produces and what is deployed.
FROM base AS runtime
ARG PORT=8000
# A fixed, unprivileged user with no home directory and no login shell. Kubernetes can then enforce
# runAsNonRoot because the numeric id is known.
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

WORKDIR /app
# Application code is owned by root and not writable by the app user: a compromised process cannot rewrite it.
# Tests, dev requirements, .env files and local databases never enter the image (see the .dockerignore).
COPY app ./app
COPY alembic.ini ./
COPY migrations ./migrations

USER 10001:10001
EXPOSE ${PORT}
# Used by plain Docker and Compose. Kubernetes ignores it and uses its own liveness/readiness probes.
# Python is already here, so no curl is needed in the image.
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/health', timeout=2)"]

# Exec form: uvicorn is PID 1 and receives SIGTERM directly, so it shuts down gracefully on every deploy.
# One process per container; we scale by running more containers, not more workers inside one.
# Other commands from the SAME image:  python -m app.worker  (Notification queue consumer)
#                                      alembic upgrade head   (database migrations Job)
CMD ["uvicorn", "app.asgi:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
