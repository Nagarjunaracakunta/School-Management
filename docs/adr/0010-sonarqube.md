# ADR 0010: Code quality with SonarQube (Phase 17)

Status: Accepted
Date: 2026-10-24

| # | Decision | Reason | Revisit when |
|---|---|---|---|
| D87 | **One SonarQube project for the monorepo** (`sonar-project.properties` at the root), not one per service | One quality gate, one dashboard, one token. The services share patterns, so one view shows cross-service problems | Teams own services separately: split the project, keep the folder layout |
| D88 | A **separate workflow** (`sonarqube.yml`), not a job in `ci.yml` | SonarQube needs coverage from every service at once; `ci.yml` runs only what changed. Partial coverage would make untouched services look untested | Path filtering is dropped |
| D89 | The gate is **"clean as you code"**: conditions apply to new code only (80% coverage, no new issues, all new hotspots reviewed, at most 3% duplication) | Existing debt does not block today's work, but nothing new gets worse. Defined in `scripts/ci/sonar-quality-gate.sh`, so the rules are reviewed like code | Existing debt is paid down: tighten to overall code |
| D90 | `SONAR_TOKEN` is a GitHub **secret**; `SONAR_HOST_URL` is a **variable** | The token grants access; the address does not | Never expected |
| D91 | Fork pull requests skip the analysis | GitHub withholds secrets from forks, and handing them over would be unsafe | Never expected |
| D92 | **SonarQube complements, not replaces**, the other checks: ruff (style, fast), pytest (behaviour), Trivy and pip-audit (known vulnerabilities in dependencies and images), gitleaks (secrets). SonarQube finds bugs, code smells, insecure patterns in OUR code, and tracks coverage trends | Each tool answers a different question | Never expected |
| D93 | Migrations, tests and generated folders are excluded from analysis; lambda and db-bootstrap are analysed but excluded from the coverage percentage | Migrations are generated-style code; those two have their own test jobs and no coverage report in this workflow | They gain a coverage report |
| D94 | Self-hosting for the learning project: `docker-compose.sonar.yml` (Community Build + its own PostgreSQL, port bound to localhost). Production alternatives: SonarQube Cloud, or the server on EKS/EC2 with RDS | Free and teaches how the server works. CI needs a reachable server, so for GitHub-hosted runners use SonarQube Cloud or an HTTPS-exposed server | A team wants no server to operate |

## Setting it up

1. Local trial: `scripts/ci/sonar-local.sh start`, log in at http://localhost:9000 (admin / admin, change it), create a token, then `scripts/ci/sonar-local.sh scan <token>`.
2. For CI: a server reachable from GitHub (SonarQube Cloud or your own HTTPS server). Create the project key `school-management`, run `scripts/ci/sonar-quality-gate.sh` with an admin token, then in GitHub add the secret `SONAR_TOKEN` and the variable `SONAR_HOST_URL`.
3. Add the check `scan and quality gate` to the branch protection of `main`.
