# School Management Platform

A production-style microservices application used to learn AWS, Terraform, Kubernetes,
GitHub Actions, SonarQube, JFrog, ECR and Argo CD.

Architecture decisions: [docs/adr/0001-core-architecture-decisions.md](docs/adr/0001-core-architecture-decisions.md)

## Layout

| Path | Purpose |
|---|---|
| `frontend/` | React single-page app, built to static files and served from S3 + CloudFront |
| `services/<name>/` | Independently deployable FastAPI microservices (auth, admission, student, fee, attendance, notification) |
| `lambdas/` | Small AWS Lambda functions (overdue-fee reminder, dead-letter-queue alert) |
| `terraform/` | Infrastructure as code: `bootstrap/` (state bucket), `modules/` (reusable), `environments/` (dev, stage, prod) |
| `helm/` | One shared chart used by every service; per-environment values live in the GitOps repo |
| `docs/` | ADRs (decisions) and runbooks (troubleshooting) |
| `scripts/` | Small helper scripts |
| `.github/` | CI workflows, CODEOWNERS, PR template |

The companion repo `school-management-gitops` holds what is deployed in each environment.

## Status

Built phase by phase. Done so far: architecture, repository skeleton, React frontend, all six backend services (Auth, Admission, Student,
Fee, Attendance, Notification) the database layer (Alembic migrations, per-service schemas and roles), Docker images, Terraform, EKS, Helm and the GitHub Actions CI pipeline ([docs/ci.md](docs/ci.md)) SonarQube ([docs/sonarqube.md](docs/sonarqube.md)) and JFrog / ECR ([docs/jfrog.md](docs/jfrog.md)) and Argo CD / GitOps ([docs/argocd.md](docs/argocd.md)).

## Documentation

| Read this | If you are |
|---|---|
| [docs/developer-guide.md](docs/developer-guide.md) | writing application code: components, request flow, API rules, auth, data, events, how to run and test, how a change reaches dev |
| [docs/devops-guide.md](docs/devops-guide.md) | running the platform: AWS architecture, Terraform, containers, Kubernetes/Helm, CI, GitOps, deployment strategy, observability, troubleshooting. Written for beginners |
| [docs/deployment.md](docs/deployment.md) | deploying for the first time: the ordered runbook from an empty AWS account to a working portal, and tear-down |
| [docs/adr/](docs/adr/) | wondering *why* something was decided |

Check everything that can be checked without an AWS account (tests, lint, Terraform, Helm, workflows, secrets, and the whole platform running end to end):
`scripts/e2e/dry-run.sh --with-stack`

## Quick start (local)

Everything in Docker, one command (details in [docs/docker.md](docs/docker.md)):

```bash
scripts/local-up.sh        # then open http://localhost:8080
```

Or step by step, without containers:

```bash
# 1. PostgreSQL: either Docker ...
export PG_ADMIN_PASSWORD=<choose one> && docker compose up -d postgres
# ... or any PostgreSQL 16 you already have. Then create schemas + roles, and apply the migrations:
PGHOST=localhost PGUSER=postgres PGPASSWORD=$PG_ADMIN_PASSWORD PGDATABASE=school scripts/db/bootstrap.sh
DB_HOST=localhost scripts/db/migrate.sh

# 2. Each service also runs on a throwaway SQLite file with zero setup (see services/<name>/README.md)

# 3. Tests: fast on SQLite, and the same suites on real PostgreSQL
(cd services/fee && pytest)
PGHOST=localhost PGUSER=postgres PGPASSWORD=$PG_ADMIN_PASSWORD scripts/db/test-postgres.sh
```

Database design: [docs/database.md](docs/database.md) · decisions: [ADR 0001](docs/adr/0001-core-architecture-decisions.md),
[ADR 0002](docs/adr/0002-database-migrations-and-roles.md),
[ADR 0003](docs/adr/0003-authentication-and-tokens.md),
[ADR 0004](docs/adr/0004-container-images.md),
[ADR 0005](docs/adr/0005-terraform-structure.md),
[ADR 0006](docs/adr/0006-aws-resources.md),
[ADR 0007](docs/adr/0007-kubernetes-cluster.md),
[ADR 0008](docs/adr/0008-helm-and-secrets-in-kubernetes.md) · deploying: [docs/helm.md](docs/helm.md) · infrastructure: [docs/terraform.md](docs/terraform.md) · security model: [docs/security.md](docs/security.md)
