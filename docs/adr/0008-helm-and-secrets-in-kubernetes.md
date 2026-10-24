# ADR 0008: Helm charts, and how pods get their secrets

Status: Accepted
Date: 2026-10-24

Builds on D10 (one shared chart) and D7 (a separate GitOps repository holds what is deployed).

| # | Decision | Reason | Revisit when |
|---|---|---|---|
| D65 | **Pods read their own secrets from Secrets Manager at startup** with their Pod Identity role. The chart passes only the secrets' ARNs. There are no Kubernetes `Secret` objects and no External Secrets Operator or CSI driver | Nothing secret is stored in the cluster (etcd, backups, `kubectl get secret`). Each service can read only what its own IAM role allows, which is exactly the per-service least privilege built in Phase 13. One less component to run | Secrets must change without a restart: add a reloader or the Secrets Store CSI driver |
| D66 | A change of a secret takes effect at the **next pod restart** (a deploy, or `kubectl rollout restart`) | Reading at startup is simple and cannot fail halfway through a request | Rotation becomes frequent |
| D67 | Two charts: `school-service` (one release per service) and `school-platform` (once per namespace: the `db-migrator` service account, default-deny network policy, resource defaults, the database bootstrap job) | Shared things need exactly one owner. Two releases cannot both own the same ServiceAccount | Never expected |
| D68 | Database changes run as a **Helm hook Job** (`pre-install,pre-upgrade`) before the new version starts, using the schema-changing login through the `db-migrator` service account. In Argo CD the hook is a PreSync step | A failed migration stops the deploy and the old version keeps serving. App pods never hold DDL rights (ADR 0002) | Never expected |
| D69 | `values.schema.json` is **strict** (`additionalProperties: false`), and image tags must be a git commit SHA | A misspelt key is an error, not a silently ignored setting; "latest" cannot be deployed | Never expected |
| D70 | Per-environment values (ARNs, URLs, account ids) are **generated** from `terraform output` by `scripts/helm/render-env-values.py`; the only thing CI edits afterwards is `image.tag` | No hand-copied ARNs; the Terraform and the Helm values cannot drift apart | Never expected |
| D71 | Every pod follows the Kubernetes *restricted* profile: non-root (uid 10001), read-only filesystem with an in-memory `/tmp`, no capabilities, `RuntimeDefault` seccomp, **no Kubernetes API token** (`automountServiceAccountToken: false`) | Limits what a compromised pod can do. Our services never talk to the Kubernetes API | A workload needs the API |
| D72 | **NetworkPolicy**: the namespace denies all traffic; each service opens only what it needs (load balancer in, listed callers in; DNS, the Pod Identity agent, PostgreSQL, AWS APIs and listed callees out). The cluster's CNI is configured to enforce them | A compromised pod cannot reach other services or probe the network | Service mesh with mutual TLS |
| D73 | One shared **ALB** for all services (Ingress group). Route order matters: Fee and Attendance (order 10) are evaluated before Student (20), because `/students/{id}/fees` starts with `/students` | The ALB costs money per hour; sharing one is ~6x cheaper. The ordering rule is tested | Per-service load balancers for isolation |
| D74 | Rolling updates never remove a pod before its replacement is ready (`maxUnavailable: 0`); pods are spread across zones; a PodDisruptionBudget protects against node upgrades; pods wait 10 seconds before stopping so the load balancer stops sending them traffic | Zero-downtime deploys | Never expected |
| D75 | The overdue-fee reminder is a **CronJob of the Fee image**. It writes events to the service's own outbox; the API pods publish them | Replaces the planned Lambda (ADR 0006): no boundary crossed, no token needed | Never expected |

## What each release gets

| Service | Queue | Calls Student | Own DB login | Special |
|---|---|---|---|---|
| auth | no | no | yes | signing key |
| admission | sends events | yes | yes | |
| student | no | no (is called by admission, fee, attendance) | yes | |
| fee | sends events | yes | yes | CronJob: overdue reminders |
| attendance | sends events | yes | yes | |
| notification | reads events, publishes to SNS | no | yes | second Deployment: the queue worker |
