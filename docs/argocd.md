# Argo CD and GitOps (Phase 19)

## GitOps in one paragraph

Git is the single description of what runs. A program inside the cluster (Argo CD) keeps comparing Git with the cluster and
makes the cluster match. To deploy you **change Git**; to roll back you **change Git back**; to find out who changed
production and why, you **read the Git history**.

```
developer -> pull request -> main -> CI (test, scan, build) -> image in ECR
                                       |
                    update-deployment.yml: one-line commit  ->  helm/environments/dev/fee.yaml   tag: "<sha>"
                                                                        |
                         Argo CD (inside the cluster) polls Git, sees the change, runs helm template, applies, waits for health
```

## Why GitHub Actions does not run `kubectl` or `helm upgrade`

| With `kubectl` in the pipeline (push) | With Argo CD (pull) |
|---|---|
| GitHub needs credentials to the cluster API (a stored key, or a role that can change production) | GitHub has **no** access to the cluster. The only credential in the system that can change workloads lives inside the cluster |
| The cluster API must be reachable from GitHub's runners | The cluster API can stay private |
| Someone edits a Deployment by hand: nobody notices | Argo CD shows `OutOfSync` and (dev/stage) reverts it (`selfHeal`) |
| What runs is "whatever the last pipeline did" | What runs is what is in Git, always |
| Rollback = re-run an old pipeline and hope | Rollback = `git revert` |
| Pipeline failure half-way leaves unknown state | Argo CD retries until the cluster matches |

## Repository layout

```
helm/school-platform/, helm/school-service/    the charts (HOW to run things)         -- changed by developers
helm/services/<svc>.yaml                        what each service IS (ports, probes)    -- changed by developers
helm/environments/<env>/common.yaml             ARNs, URLs of the environment           -- generated from Terraform
helm/environments/<env>/<svc>.yaml              image tag, replicas, size               -- THE deployment record; CI edits `tag:` only
argocd/install/values.yaml                      how Argo CD itself is installed
argocd/envs/<env>/bootstrap/project.yaml        AppProject: what this Argo CD may deploy, from where, to where
argocd/envs/<env>/bootstrap/root.yaml           the root Application (apply once)
argocd/envs/<env>/apps/*.yaml                   one Application per release (platform + 6 services)
scripts/argocd/render_apps.py                   generates argocd/envs/** (do not edit those by hand)
scripts/ci/bump_image_tag.py                    the only code that edits tags
```
Decision D7 planned a *separate* GitOps repository. For learning, one repository is simpler; ADR 0012 explains the trade-off
and the one-line change that moves the values to their own repository later.

## App of apps

```
school-dev-root  (you apply it once)         watches argocd/envs/dev/apps/
 |- school-dev-platform     wave 0   namespace, db-migrator account, network policy, database bootstrap (a PostSync job)
 |- school-dev-auth         wave 1
 |- school-dev-student      wave 1
 '- admission, fee, attendance, notification   wave 2
```
A wave starts only when the previous wave is **Healthy**, so the database roles exist before any service tries to migrate.
Each service's migration is a Helm `pre-upgrade` hook; Argo CD runs it as a **PreSync** step: if the migration fails the
sync stops and the old pods keep serving (ADR 0008, D68).

Each Application has two **sources**: the chart, and the values files (`ref: values`, read as `$values/...`). That is what lets
chart and values live in different repositories.

| | dev | stage | prod |
|---|---|---|---|
| Sync | automatic, prune, self-heal | automatic, prune, self-heal | **manual**: a person presses Sync |
| How a tag arrives | bot commit after every build | pull request from "Update deployment configuration" | pull request, then Sync |
| Deleting the Application deletes the workload | yes (finalizer) | yes | **no** (no finalizer) |

## Install (once per cluster)

```bash
aws eks update-kubeconfig --name school-dev --region ap-south-1
scripts/argocd/render_apps.py --repo-url https://github.com/<you>/school-management.git     # put your real URL in the files, commit
scripts/argocd/install.sh dev
kubectl -n argocd get applications            # school-dev-root, then the seven children appear
kubectl -n argocd port-forward svc/argocd-server 8080:443        # https://localhost:8080 , user admin
```
A private repository needs read access. Create a **deploy key** (read-only) or a GitHub App, and register it from your
terminal; the key never goes into Git:
```bash
argocd login localhost:8080 --username admin --insecure
argocd repo add https://github.com/<you>/school-management.git --ssh-private-key-path ~/.ssh/school-deploy-key   # SSH URL form: git@github.com:<you>/school-management.git
argocd repo list
```
Delete the initial admin secret once SSO or another admin exists: `kubectl -n argocd delete secret argocd-initial-admin-secret`.

## The daily flow

1. Merge a change to `services/fee/**`.
2. `Build and push images` builds, scans and pushes `school/fee:<sha>` to ECR.
3. `Update deployment configuration` commits `tag: "<sha>"` to `helm/environments/dev/fee.yaml`.
4. Argo CD (within ~3 minutes, or at once with `argocd app sync`) runs the migration hook, then rolls the pods.
5. Promote: Actions, *Update deployment configuration*, Run workflow (from dev to stage). Review and merge the pull request.
   Repeat from stage to prod; then in prod press Sync (UI, or `argocd app sync school-prod-fee`).

Repository settings this needs: Actions may push to `main` (add the bot to the branch-protection bypass list **for dev's tag file only** by
using a rule on `helm/environments/dev/**`, or use a GitHub App token), and *Allow GitHub Actions to create pull requests*.
Commits made with the built-in token do not start other workflows, so the promotion pull request shows no checks: that is a GitHub
loop-prevention rule. For real use create the pull request with a GitHub App token.

## Commands

```bash
argocd app list
argocd app get school-dev-fee                       # health, sync status, the image running, recent events
argocd app diff school-dev-fee                      # what Git says vs what the cluster has
argocd app sync school-prod-fee                     # the prod approval step
argocd app history school-dev-fee
argocd app resources school-dev-fee
kubectl -n argocd logs deploy/argocd-repo-server --tail=50       # chart rendering problems
kubectl -n argocd logs statefulset/argocd-application-controller --tail=50   # sync problems
scripts/argocd/render_apps.py --check               # are the committed Application files what the generator makes?
scripts/ci/bump_image_tag.py promote --from dev --to stage       # what the promotion workflow runs
```

## Rollback

| Situation | Do | Why |
|---|---|---|
| A bad release (any environment) | `git revert <the deploy commit>`, merge | Git stays the truth; Argo CD rolls back with the same migration and health checks as any deploy. **The normal way** |
| Emergency, seconds matter, dev/stage | revert anyway (it is two clicks); do not use `argocd app rollback` | With auto-sync on, Argo CD refuses a manual rollback, and would undo it |
| Emergency in prod (manual sync) | `argocd app rollback school-prod-fee <ID from history>`, THEN revert in Git | The cluster is fixed first; Git is brought back in line right after, or the next sync redeploys the bad version |
| Pods only, Git is fine | `kubectl -n school-prod rollout undo deploy/fee` | Argo CD will show OutOfSync (prod: manual) until Git agrees; use only as a stopgap |

Database migrations are not undone by a rollback. They are written "expand, then contract" (ADR 0002), so the previous version
still works against the new schema.

## Troubleshooting

| Symptom | Check | Cause and fix |
|---|---|---|
| Application `OutOfSync`, and you did not change Git | `argocd app diff <app>` | someone edited the cluster by hand (dev/stage: self-heal reverts it; prod: sync, or put the change in Git); or a field the cluster fills in (add it to `ignoreDifferences`) |
| `OutOfSync` forever, diff shows only `spec.replicas` | `argocd app diff` | an autoscaler owns replicas: the `ignoreDifferences` rule above; check it is present |
| `ComparisonError: ... values file ... not found` | `kubectl -n argocd logs deploy/argocd-repo-server` | a path in `valueFiles` is wrong, or the file is on a branch Argo CD does not read. Run `render_apps.py --check` |
| `repository not found` / authentication | `argocd repo list` | repository credentials missing or wrong; re-add the deploy key |
| `Health: Progressing` for a long time | `argocd app get`, then `kubectl -n school-dev get pods` | pods not Ready: see docs/helm.md (ImagePullBackOff means the tag is not in ECR: the bump ran before the push finished, or the build failed) |
| Sync fails at PreSync (`fee-migrate`) | `kubectl -n school-dev logs job/fee-migrate` | the migration failed; the old version keeps running. Fix forward or revert |
| Services stuck behind wave 0 | `argocd app get school-dev-platform` | the database bootstrap job (PostSync) failed: `kubectl -n school-dev logs job/db-bootstrap` |
| `project ... is not permitted to deploy to cluster/namespace` | the AppProject | the project allows only `school-<env>` on this cluster |
| Sync is `Unknown` / `Sync window` | `argocd proj windows list school-prod` | a sync window denies syncs |
| Dev bump job fails to push | the job log | branch protection blocks the bot (see settings above) |
