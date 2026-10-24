# syntax=docker/dockerfile:1
# The small image that creates database schemas and roles (Job in the school-platform Helm chart).
#
#   docker build -f docker/db-tools.Dockerfile -t school/db-tools:dev tools/db-bootstrap
#   docker build -f docker/db-tools.Dockerfile --target test tools/db-bootstrap     # its tests (the ones needing no database)
ARG PYTHON_VERSION=3.12

FROM python:${PYTHON_VERSION}-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

FROM base AS builder
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"
COPY requirements.txt .
RUN pip install -r requirements.txt

FROM builder AS test
COPY requirements-dev.txt .
RUN pip install -r requirements-dev.txt
WORKDIR /src
COPY . .
RUN pytest -q -p no:cacheprovider

FROM base AS runtime
RUN groupadd --system --gid 10001 app && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"
WORKDIR /app
COPY bootstrap.py .
USER 10001:10001
CMD ["python", "bootstrap.py"]
