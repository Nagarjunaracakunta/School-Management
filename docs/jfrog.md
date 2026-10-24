# JFrog Artifactory and Amazon ECR (Phase 18)

## The difference

| | Amazon ECR | JFrog Artifactory |
|---|---|---|
| What it stores | container images (OCI) only | anything: Python/npm packages, Helm charts, zip/tar files, Docker images, Maven, ... |
| What it is good at | pulling images into EKS: same AWS account, IAM auth, no extra network hop, image scanning, lifecycle rules | one place for ALL artifact types; proxying and caching public registries; promotion between repositories; build info; Xray scanning of every type |
| Cost / operation | cheap, nothing to run | a product to license (SaaS or self-hosted) |
| Who authenticates | IAM | JFrog tokens, or an OIDC integration |

## What goes where in this project

| Artifact | Stored in | Why |
|---|---|---|
| The six service images, `db-tools` | **ECR** `school/<name>:<git sha>` | EKS pulls from ECR over AWS's network with the node's IAM role. Putting images only in JFrog would make every pod start depend on an external service |
| Python packages (what `pip install` downloads) | **JFrog**, through `school-pypi` (proxy of pypi.org) | cached copies survive a PyPI outage; one place to block a bad package; one audit trail |
| npm packages | **JFrog**, through `school-npm` | same |
| Frontend bundle `frontend-dist-<sha>.tar.gz` | **JFrog** `school-generic-local/frontend/<sha>/` | built once and deployed unchanged to every environment; the checksum file proves the file was not altered |
| Helm charts `school-service-0.1.0-sha.<sha>.tgz` | **JFrog** `school-helm-local` | versioned, immutable chart packages. (Argo CD in Phase 19 reads the charts straight from Git; the packages are for sharing and audit) |
| SBOMs | workflow artifact (30 days) today | would move to JFrog if Xray were licensed |
| Notification Lambda | neither | Terraform packages it from source at apply time, so a stored zip would never be used |
| Terraform state | S3 | not a build artifact |

Not forcing JFrog into the path of images is deliberate: see [ADR 0011](adr/0011-artifact-management.md).

## The four "repositories" in the pipeline

| Name | Holds | Here |
|---|---|---|
| Source repository | code and its history | GitHub |
| Artifact repository | built files and cached dependencies | JFrog Artifactory |
| Container registry | runnable images | Amazon ECR |
| Deployment repository | what should be running, per environment | the GitOps repo (Phase 19) |

## Setup

```bash
# 1. Create the repositories (files in jfrog/)
JF_URL=https://acme.jfrog.io JF_ADMIN_TOKEN=... scripts/ci/jfrog-setup.sh
```
2. In JFrog, Administration, Authentication Settings, **OIDC integration**: provider type GitHub, name e.g. `github-school`, identity mapping on claim `repository = OWNER/school-management` and `environment = artifact-publish`, mapped to a user that may deploy to `school-generic-local` and `school-helm-local` only.
3. In GitHub: create the Environment `artifact-publish` (main branch only); add the **variables** `JFROG_URL` and `JFROG_OIDC_PROVIDER`. No secret is needed.

## Using the proxy for dependencies (optional, recommended)

```bash
# a developer, or a CI step (the token comes from a secret, never from the repository)
pip install -r requirements.txt --index-url "https://$JF_USER:$JF_TOKEN@acme.jfrog.io/artifactory/api/pypi/school-pypi/simple"
npm config set registry https://acme.jfrog.io/artifactory/api/npm/school-npm/
```
CI keeps using pypi.org directly until you decide to turn this on; it is a one-line change per job.

## Commands

```bash
jf config add school --url https://acme.jfrog.io --access-token "$JF_TOKEN"   # local login
jf rt ping                                                                    # reachable and authenticated?
jf rt search "school-generic-local/frontend/*"                                # what is stored
jf rt download "school-generic-local/frontend/<sha>/frontend-dist-<sha>.tar.gz" ./
sha256sum -c frontend-dist-<sha>.tar.gz.sha256                                # not altered?
helm repo add school https://acme.jfrog.io/artifactory/api/helm/school-helm-local --username "$JF_USER" --password "$JF_TOKEN"
helm search repo school --devel                                               # --devel shows the -sha.<commit> versions
```

## Troubleshooting: artifact upload or download fails

| Symptom | Likely cause | Check / fix |
|---|---|---|
| `Failed to exchange OIDC token` / 401 in setup | the OIDC integration's claims do not match | compare the integration's conditions with the job: repository, environment name `artifact-publish`, branch. The job must be on `main` |
| `jf rt ping` fails, connection error | wrong `JFROG_URL` (no trailing path), or an IP allow-list blocks GitHub runners | `curl -I $JFROG_URL/artifactory/api/system/ping` |
| 403 on upload | the mapped user cannot deploy to that repository | JFrog: Administration, Permissions |
| 409 / "already exists" on chart upload | the repository is set to forbid overwrite and the same version was uploaded | expected on a re-run: versions contain the commit, so a re-run of the same commit is the only cause; ignore or delete that version |
| 404 on download | wrong path: the SHA differs, or the file was never uploaded because the frontend did not change in that commit | `jf rt search` for the real path; use the SHA of the last commit that touched `frontend/` |
| pip/npm 401 behind the proxy | expired token | create a new access token, update the secret |
| pip downloads work but a package is "blocked" | an Xray policy blocked a vulnerable or unapproved package | the message names the policy; pick another version |
