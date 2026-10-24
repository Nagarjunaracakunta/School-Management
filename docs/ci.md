# Continuous integration (Phase 16)

## The workflows

| File | When | What it does |
|---|---|---|
| `ci.yml` | every pull request, push to `main`, manual | detects what changed, then lints and tests only that: services (`_service.yml`), frontend, Terraform, Helm, lambda, db-bootstrap, CI scripts, workflow lint (actionlint), secret scan (gitleaks). `ci-gate` summarises |
| `_service.yml` | called by `ci.yml` once per changed service | ruff, pytest with coverage floor (85%), pytest on real PostgreSQL, Docker `test` stage, runtime image checks (non-root, no tests, no dev tools), Trivy scan |
| `build-images.yml` | push to `main`, manual | builds the changed images for linux/amd64, scans, pushes to ECR tagged with the commit SHA, records digest and SBOM |
| `security.yml` | Mondays, and when dependency or infrastructure files change | pip-audit, npm audit, Trivy configuration scan |

## Who does what

| Concept | Is | In this project |
|---|---|---|
| Source repository | the code | GitHub |
| CI | builds and tests | GitHub Actions |
| Container registry | runnable images | Amazon ECR (Phase 18 explains JFrog's role) |
| Deployment repository | what should run | the GitOps repository (Phase 19) |

## Try the pieces locally

```bash
python3 scripts/ci/changed.py --base origin/main --head HEAD     # what would CI run for my branch?
python3 -m pytest -q scripts/ci/tests                            # tests of that script
scripts/tf/check.sh                                              # the Terraform job
scripts/helm/check.sh                                            # the Helm job
cd services/fee && pip install -r requirements-dev.txt && ruff check app tests migrations && pytest -q
docker build -f docker/python-service.Dockerfile --target test services/fee    # the in-image test run
actionlint                                                       # lint the workflows (brew install actionlint)
```

## Reading a failure

| Symptom | Look at | Usual cause |
|---|---|---|
| `ci-gate` red, others green | the `NEEDS` table in its log | a job was cancelled or timed out |
| coverage below 85% | `pytest` step output, `coverage-<service>` artifact | new code without tests |
| Trivy HIGH/CRITICAL | the scan step table | upgrade the package in `requirements.txt` (or the base image); only if no fix exists add to `.trivyignore` with reason and expiry |
| `Could not assume role` / `Not authorized to perform sts:AssumeRoleWithWebIdentity` | token subject in the error vs terraform output `subject` | job is not in the `registry-push` environment, branch is not `main`, wrong repo name in tfvars |
| `tag invalid: ... immutable` | ECR | the SHA was already pushed; the `exists` step should have skipped; check it ran |
| `no basic auth credentials` | `amazon-ecr-login` step | role lacks `ecr:GetAuthorizationToken` or region variable wrong |
| gitleaks finding | the redacted output | rotate the secret FIRST, then remove it; history is scanned |
