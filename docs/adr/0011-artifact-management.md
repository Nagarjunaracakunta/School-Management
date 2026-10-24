# ADR 0011: Artifact management, JFrog and ECR (Phase 18)

Status: Accepted
Date: 2026-10-24

| # | Decision | Reason | Revisit when |
|---|---|---|---|
| D95 | **Container images live in ECR only** | The cluster pulls from ECR over AWS's network using the node role (ADR 0007). A second registry in the pull path adds a dependency and credentials for no gain | A company standard requires one registry for everything: then ECR becomes a replica of JFrog |
| D96 | JFrog Artifactory holds the **non-image build outputs**: frontend bundle, Helm chart packages | Artifactory is built for many artifact types and keeps who/when/which commit | Never expected |
| D97 | JFrog is also the **dependency proxy** for PyPI and npm (virtual repositories `school-pypi`, `school-npm`), adopted per job when wanted | Builds survive a public registry outage and one place can block a bad package. Optional: CI works without it | A supply-chain incident, or Xray is licensed |
| D98 | **No JFrog API keys.** GitHub authenticates with OIDC; the mapped user can deploy only to the two local repositories | Same reasoning as D81 | Never expected |
| D99 | One **build** per workflow run is published to Artifactory (build info with git commit and environment) | Traceability: from a file in the repository back to the commit and run | Never expected |
| D100 | Artifact names contain the **git commit SHA**; charts use the semantic version `<chart version>-sha.<short sha>`; the bundle has a published SHA-256 | Same identifier as the image tag (D69), so one commit names every artifact built from it | Never expected |
| D101 | The frontend bundle is **environment-neutral** (calls the relative `/api/v1`) so the same file is deployed to every environment | "Build once, promote the same bytes". Anything per environment is configuration at the edge (CloudFront and ALB), not baked in | The app needs build-time environment values |
| D102 | The Lambda is **not** published to JFrog | Terraform packages it from source at apply time; storing a copy nobody consumes is noise | Lambdas are deployed by a pipeline instead of Terraform |
| D103 | Repositories are defined as JSON files in `jfrog/` and applied by `scripts/ci/jfrog-setup.sh` | Reviewed like code. In a larger organisation use the JFrog Terraform provider | The team already manages JFrog with Terraform |

Layout of the Artifactory repositories (naming `<project>-<type>-<local|remote>`):
`school-generic-local`, `school-helm-local`, `school-pypi-remote` + `school-pypi` (virtual), `school-npm-remote` + `school-npm` (virtual).
