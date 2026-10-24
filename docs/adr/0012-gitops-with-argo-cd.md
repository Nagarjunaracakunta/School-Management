# ADR 0012: GitOps with Argo CD (Phase 19)

Status: Accepted
Date: 2026-10-24

Amends D7 (separate GitOps repository) for the learning project only.

| # | Decision | Reason | Revisit when |
|---|---|---|---|
| D104 | **Pull, not push.** Argo CD runs inside each environment's cluster and pulls from Git. No pipeline holds cluster credentials | The cluster API stays private; no key to leak; drift is detected and (dev/stage) reverted | Never expected |
| D105 | **One Argo CD per cluster** (dev, stage, prod each have their own) | Blast radius: a problem in dev's Argo CD cannot touch prod. Matches one AWS account per environment (ADR 0005) | Many clusters: a central Argo CD managing them, with the AppProject per environment unchanged |
| D106 | **The deployment record is `helm/environments/<env>/<service>.yaml`**; CI changes only the `tag:` line, through `scripts/ci/bump_image_tag.py`, which accepts only full 40-character commit SHAs | A tag is one reviewable line; "latest" cannot be deployed; promotion is a diff | Never expected |
| D107 | **Same repository for charts and values, for now** (amends D7). The Applications already use two sources, so moving the values to a separate repository is: create the repository, move `helm/environments/`, change the second source's `repoURL` and the paths in the bump script | One repository is far easier to learn from and to run tests across. D7's concern (a bump commit retriggering CI) does not arise: a values-only change builds no image, and commits made with the built-in token start no workflow | More than one team, or prod approvals need a different set of people than code reviews |
| D108 | **App of apps**: one root Application per environment creates the platform and six service Applications, with sync waves (platform, then auth and student, then the rest) | One command bootstraps an environment; ordering is explicit. ApplicationSet was considered: its ordering feature is still alpha | Many environments or tenants: ApplicationSet |
| D109 | **The Application files are generated** (`render_apps.py`) and CI fails if they differ | Seven applications times three environments is 21 near-identical files that would drift | Never expected |
| D110 | **dev and stage sync automatically with prune and self-heal; prod does not**: a person presses Sync after the pull request is merged | Prod needs a human gate and a chosen moment; auto-sync for the lower environments gives fast feedback | The team trusts the pipeline: prod can follow stage automatically with a sync window |
| D111 | **AppProject per environment**: one repository allowed, one namespace allowed, no cluster-wide objects except the Namespace | A mistake or compromise in a manifest cannot create cluster roles or deploy elsewhere | Never expected |
| D112 | **Promotion is a pull request** (dev to stage to prod, never skipping) created by a manual workflow; merging it is the approval; `CODEOWNERS` names who may approve prod | Auditable, reviewable, and uses the tools the team already knows | Never expected |
| D113 | **Rollback is `git revert`**; `argocd app rollback` only as an emergency in prod, followed by a revert | Git must stay the truth | Never expected |
| D114 | Prod Applications have **no deletion finalizer** | Deleting an Application object by mistake must not delete the running service | Never expected |
