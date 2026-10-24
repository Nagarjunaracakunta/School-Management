# ADR 0009: Continuous integration with GitHub Actions (Phase 16)

Status: Accepted
Date: 2026-10-24

Builds on D7 (a separate GitOps repository holds what is deployed) and D69 (image tags are git commit SHAs).

| # | Decision | Reason | Revisit when |
|---|---|---|---|
| D76 | **Path-aware CI** (`scripts/ci/changed.py`): only the services, charts and modules a change touches are tested. A change to a shared file re-tests every service. If the diff cannot be computed, everything runs | A monorepo with six services would otherwise run 6x the work on every pull request. A check skipped by mistake is worse than one run unnecessarily, so the script fails open | Build times stay low without it |
| D77 | **One required check: `ci-gate`**. It depends on every job and accepts only `success` or `skipped` | Branch protection lists one name; adding a job never needs a settings change. Skipped jobs (nothing changed) do not block a merge | Never expected |
| D78 | Tests run **twice**: on the runner (fast tests on a throwaway SQLite file) with a coverage floor of 85%, and on a real PostgreSQL 16 service container; then again **inside the image build** (Docker target `test`) | The same database engine as RDS catches locking and migration bugs; the in-image run proves the shipped dependency set works on Python 3.12 | Never expected |
| D79 | **Every third-party action is pinned to a commit SHA**, with the version in a comment. Dependabot proposes updates weekly | A tag can be moved; a SHA cannot. Supply-chain attacks on actions are real | Never expected |
| D80 | Workflow permissions default to `contents: read`. Only the image-push job gets `id-token: write`, and only inside the `registry-push` GitHub Environment | Least privilege for the pipeline itself | Never expected |
| D81 | **No AWS access keys.** GitHub proves its identity with an OIDC token; the role (`terraform/modules/github-oidc`) trusts exactly `repo:OWNER/REPO:environment:registry-push` and can only push to our ECR repositories | Nothing to leak or rotate; a fork or another branch cannot obtain the role | Never expected |
| D82 | Images are built **once per commit on `main`**, scanned with Trivy (HIGH/CRITICAL with a fix fail the build), pushed with the commit SHA as the immutable tag, and the SBOM is stored as an artifact. The scanned image is the pushed image | "Build once, promote the same bytes" through dev, stage and prod | Never expected |
| D83 | A re-run never pushes twice: the job first asks ECR whether the SHA tag exists | ECR tags are immutable, so a second push would fail; skipping makes re-runs safe | Never expected |
| D84 | CI **does not deploy**. It stops at "image in ECR". Updating the image tag in the GitOps repository (Phase 19) and Argo CD (Phase 19) do the rest | GitHub never holds cluster credentials (GitOps) | Never expected |
| D85 | Security scans (pip-audit, npm audit, Trivy misconfiguration) also run **weekly** | New vulnerabilities appear without any code change | Never expected |
| D86 | SonarQube and JFrog are **not** in Phase 16. They are added in Phases 17 and 18 as extra jobs, reading the `coverage.xml` the service jobs already upload | Each tool is introduced with its own explanation, and the pipeline is already useful without them | Phases 17 / 18 |

## One-time setup in GitHub

1. Create the Environment `registry-push` (Settings, Environments) and allow deployments from `main` only.
2. After `terraform apply` in `environments/dev`, copy the output `github_ecr_push_role_arn` into the repository variable `AWS_ECR_PUSH_ROLE_ARN`, and set the variable `AWS_REGION` (for example `ap-south-1`).
3. Protect `main`: require a pull request and the status check `ci-gate`.
