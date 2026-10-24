# DevOps guide: how the School Management Platform is built, shipped and run

Written so that someone new to DevOps can follow it from top to bottom. Every term is explained the first time it appears (there is also a glossary at the end). Where something is **not built yet** or **has not been tried on a real AWS account**, the text says so.

Companion documents: [developer-guide.md](developer-guide.md) (the application) · [deployment.md](deployment.md) (the step-by-step first deployment) · [adr/](adr/) (why each decision was made).

Contents
1. The 10-minute picture
2. Repository map
3. Environments and accounts
4. The runtime architecture, service by service
5. Network and security layers
6. Terraform (infrastructure as code)
7. Containers
8. Kubernetes and Helm
9. CI: from commit to image
10. CD: GitOps with Argo CD
11. Deployment strategy
12. Observability
13. Troubleshooting by layer (16 scenarios)
14. Day-to-day operations
15. Cost, backup, disaster recovery
16. Decisions, trade-offs and what an enterprise would add
17. Command cheat sheet
18. Glossary

---

## 1. The 10-minute picture

### What are we running?
A website (React, static files) and six small programs (Python "services") that the website calls. They store data in one database and announce events through a queue.

### Two journeys to understand

**Journey A: a user's request (runtime).** Something a parent does in the browser.
```
Browser ─HTTPS─▶ CloudFront ─┬─ "/"      ─▶ S3 bucket (the website's files)
 (CDN: a worldwide cache     └─ "/api/*" ─▶ Application Load Balancer (ALB) ─▶ Kubernetes Service ─▶ Pod (a Python service)
  that also terminates TLS)                                    (public subnets)       (private subnets)        │
                                                                                                        ├─▶ PostgreSQL (RDS, database subnets)
                                                                                                        └─▶ SQS queue ─▶ worker ─▶ SNS ─▶ Lambda ─▶ email / SMS
```

**Journey B: a developer's change (delivery).** How code becomes running software. This is "the pipeline".
```
Developer ─▶ GitHub (pull request) ─▶ GitHub Actions (CI): lint · test · SonarQube · build image · scan
                                          │ merge to main
                                          ▼
                              image pushed to Amazon ECR, tagged with the Git commit SHA
                                          │
                      Actions commits that tag into  helm/environments/dev/<service>.yaml   ◀── the "deployment record" (Git)
                                          │
                       Argo CD (running inside the cluster) notices the Git change
                                          │  runs the database migration, then rolls out new pods
                                          ▼
                                    EKS cluster (Kubernetes)
```
The key idea of Journey B is **GitOps**: Git is the single description of what should run, and a robot inside the cluster makes reality match it. Nobody types `kubectl apply` on production.

### Why these choices (the short version)
| Choice | Reason |
|---|---|
| Static website on S3 + CloudFront, **not** in Kubernetes | Static files need no server. S3 costs cents, CloudFront serves from a nearby location, nothing to patch or scale. Running nginx pods for files would add cost and failure modes for no benefit. |
| One entry point (CloudFront) for both website and API | One domain and one certificate; the browser never makes a cross-origin call (no CORS). |
| ALB, **no API Gateway** in the main path | The ALB already routes by URL path. API Gateway would be a second router in a row (more cost, more latency, more to configure). Add it only for third-party API consumers who need keys/quotas. |
| Kubernetes (EKS) for the services | Many small services with rolling updates, health checks, autoscaling and self-healing is what Kubernetes is for. |
| Queue between services and notifications | A slow email provider must never slow down or break a payment. |
| Terraform for AWS, Helm for Kubernetes, Argo CD for deployment | Everything is code in Git: reviewable, repeatable, reversible. |

---

## 2. Repository map

One repository ("monorepo") holds everything. Reason: one pull request can change a service, its chart and its infrastructure together; one place to search; simpler for learning. The alternative (many repositories) gives independent permissions and release cycles but needs more tooling; revisit it when several teams own different services.

```
school-management/
├── frontend/              React app (Vite)                                  ──▶ built to static files
├── services/              auth · admission · student · fee · attendance · notification   (Python, FastAPI)
├── lambdas/               notification_delivery  (SNS → email/SMS)
├── tools/db-bootstrap/    program that creates database schemas and logins (runs as a Kubernetes Job)
├── docker/                Dockerfiles: python-service (all six services), db-tools, nginx config for local use
├── terraform/
│   ├── bootstrap/         creates the bucket that stores Terraform state (run once per account)
│   ├── modules/           reusable building blocks: vpc, eks, rds, sqs, sns, ecr, s3, cloudfront, iam, secrets, lambda, observability, github-oidc
│   └── environments/      dev · stage · prod  (same .tf files; only terraform.tfvars and backend settings differ)
├── helm/
│   ├── school-service/    ONE chart used by all six services
│   ├── school-platform/   once-per-environment parts (network policy, DB bootstrap job)
│   ├── services/          values: what each service IS
│   ├── environments/      values: what each environment IS and which image version runs there   ◀── Argo CD watches this
│   └── addons/            values for cluster add-ons (load balancer controller, metrics-server)
├── argocd/                Argo CD install values + generated Application files for each environment
├── .github/workflows/     the pipelines (ci, build-images, update-deployment, deploy-frontend, publish-artifacts, sonarqube, security)
├── jfrog/                 definitions of the artifact repositories
├── scripts/               helper scripts (tf/, helm/, argocd/, ci/, aws/, e2e/)
└── docs/                  these documents + adr/ (decision records) + per-topic guides
```

**The four "repositories" people confuse**

| Name | Holds | Here |
|---|---|---|
| Source repository | code | GitHub |
| Artifact repository | built files and cached dependencies | JFrog Artifactory (frontend bundle, Helm packages, dependency proxy) |
| Container registry | runnable images | Amazon ECR (images are *not* in JFrog; see §9) |
| Deployment repository | what should run where | the `helm/environments/` folder in Git (can move to its own repository later) |

---

## 3. Environments and accounts

| | dev | stage | prod |
|---|---|---|---|
| Purpose | integration; every merge lands here | rehearsal identical to prod | real users |
| AWS account | its own (owns the image registry) | its own | its own |
| Network | one NAT gateway (cheaper) | one NAT | one NAT **per zone** (survives a zone failure) |
| Database | `db.t4g.micro`, single AZ, 1-day backups | `db.t4g.small`, 7 days | `db.t4g.medium`, **Multi-AZ**, 14 days, deletion protection |
| Worker nodes | t3.medium, 1-3 | t3.medium, 2-4 | m5.large, 3-6 |
| Argo CD sync | automatic | automatic | **manual** (a person presses Sync) |
| Kubernetes namespace | `school-dev` | `school-stage` | `school-prod` |
| Terraform state | own bucket in own account | own | own |

Why separate AWS accounts? An account is the strongest boundary AWS offers: a mistake, a leaked key or a budget overrun in dev cannot touch prod.

**Nothing environment-specific is hardcoded.** It lives in exactly three places: `terraform/environments/<env>/terraform.tfvars`, `helm/environments/<env>/*.yaml`, and GitHub Environment variables. The Helm values with ARNs and URLs are *generated* from Terraform outputs (`scripts/helm/render-env-values.py`), so they cannot be mistyped.

**Promotion** = copying the image tag, never rebuilding. The exact bytes tested in dev are what reach prod ("build once, promote").
```
merge ─▶ image abc123 in ECR ─▶ dev runs abc123 ─▶ (PR) stage runs abc123 ─▶ (PR) prod runs abc123 (then a person presses Sync)
```
Stage and prod pull the image from dev's registry (the registry has a policy that allows the other accounts to *pull*).

---

## 4. The runtime architecture, service by service

For every AWS service: why, what uses it, how traffic flows, how it is secured, what happens when it fails.

### 4.1 VPC, subnets, gateways
* **Why:** a private network in AWS where only what we choose is reachable. **Problem solved:** by default nothing should be reachable from the internet except the front door.
* **Layout (per environment, 2-3 availability zones = separate data centers):**

  | Subnet tier | Contains | Route to the internet |
  |---|---|---|
  | public | the load balancer, NAT gateway | directly through the **Internet Gateway** |
  | private | Kubernetes worker nodes and pods | outbound only, through the **NAT gateway** (to pull updates, call AWS APIs) |
  | database | PostgreSQL | none at all |
* **Security:** security groups (virtual firewalls) are "closed until opened": the database accepts connections **only from the cluster's security group**; the load balancer accepts **only from CloudFront** (via AWS's managed prefix list of CloudFront addresses). Private S3 traffic uses a free gateway endpoint; prod also has private endpoints for ECR, STS, Secrets Manager, SQS, SNS and CloudWatch Logs so that traffic never leaves AWS's network. Prod enables VPC flow logs.
* **If it fails:** a zone failure takes down that zone's subnets; with 2-3 zones the rest keeps serving. If the single NAT (dev/stage) fails, pods cannot reach AWS APIs outbound (they keep serving cached/ready work but cannot start new pods that must pull images). Prod has one NAT per zone for this reason.

### 4.2 CloudFront + S3 (the website)
* **Why / problem:** deliver the React files quickly and securely. S3 stores them (private bucket); CloudFront is the only reader (Origin Access Control).
* **Flow:** `GET /` → CloudFront (cached) → S3 on miss. `/api/*` and `/.well-known/*` → the load balancer, with caching **disabled** and the `Authorization` header forwarded. A small CloudFront Function rewrites unknown paths to `/index.html` for the single-page app **only** on the static behaviour (so an API 404 is never turned into HTML).
* **Security:** HTTPS only (HTTP redirected), security headers (HSTS etc.) added to every response, bucket fully private and encrypted, optional custom domain + ACM certificate.
* **Caching strategy for deploys:** files in `assets/` have fingerprints in their names → cached for a year; `index.html` is `no-cache` and invalidated at each deploy.
* **If it fails:** S3 and CloudFront are managed, multi-zone. A bad deploy is fixed by re-deploying the previous commit (`Deploy frontend` workflow with an older SHA).
* **Dev without a domain:** CloudFront reaches the load balancer over plain HTTP (guardrails forbid this outside dev). With a domain, the ALB gets an ACM certificate and CloudFront connects over HTTPS.

### 4.3 Application Load Balancer (ALB)
* **Why:** one stable address that routes by URL path to the right service and health-checks every pod. **Created by Kubernetes**, not Terraform: the AWS Load Balancer Controller reads our `Ingress` objects and builds the ALB. One ALB is shared by all six services (an "ingress group"), ~6× cheaper than one each.
* **Routing order matters:** `/students/{id}/fees` begins with `/students`, so fee and attendance rules have a lower order number and are evaluated first. Tests in `helm/tests` prove every URL reaches the intended service.
* **Health checks:** the ALB calls `/ready` on each pod; only ready pods get traffic.
* **Security:** its security group allows only CloudFront; it forwards to pods on port 8000 only.
* **If it fails:** managed and multi-zone. Symptom of misconfiguration is 502/503/504 from CloudFront (see §13, scenarios 10-11).

### 4.4 EKS (Kubernetes) and worker nodes
* **Why:** runs and supervises the containers. Self-healing (restarts crashed pods), rolling updates, autoscaling, scheduling across zones.
* **Built by Terraform:** the control plane (managed by AWS, ~USD 73/month per cluster), a managed node group in private subnets (IMDSv2 only, encrypted disks, no SSH), add-ons (VPC CNI with NetworkPolicy support, kube-proxy, CoreDNS, Pod Identity agent), a KMS key that encrypts Kubernetes Secrets, and control-plane logs to CloudWatch (api, audit, authenticator, controllerManager, scheduler).
* **Access:** no one is cluster-admin by default; "access entries" grant IAM roles. The API endpoint is reachable from the internet **only from listed addresses** (never `0.0.0.0/0`), and always from inside the VPC.
* **What Terraform does not install:** things inside the cluster (load balancer controller, metrics-server, Argo CD, our apps). Those are Helm/Argo's job.
* **If it fails:** control-plane outage = you cannot deploy or `kubectl`, but running pods keep serving. Node loss = Kubernetes reschedules the pods onto other nodes (so run ≥2, prod ≥3, spread across zones).

### 4.5 RDS PostgreSQL
* **Why:** a managed relational database: backups, patches, failover. **One instance, one schema and one login per service.** No service can read another's tables; foreign keys never cross schemas.
* **Passwords:** the admin password is created and rotated *by RDS itself* in Secrets Manager (it never appears in Terraform state). Each service's login is generated by Terraform using ephemeral/write-only values (also never in state).
* **Roles:** two logins per service: `<svc>_app` (read/write rows only) and `<svc>_migrator` (can change tables; used only by the migration job).
* **Security:** private database subnets, no public address, encrypted at rest, TLS required, firewall opened only to the cluster.
* **If it fails:** prod is Multi-AZ (automatic failover to a standby in another zone, ~1-2 minutes); dev/stage are single-AZ (restore from backup). Services report not-ready (`/ready` → 503) and recover on their own when the database returns. Alarms: CPU, free storage, connections.

### 4.6 SQS, SNS, Lambda, SES (asynchronous notifications)
```
fee pod ──(1 DB transaction: payment + outbox row)──▶ relay thread ──▶ SQS "events" queue ──▶ notification worker ──▶ SNS topic ──▶ Lambda ──▶ SES email / SNS SMS
                                                            │ after 3 failed receives
                                                            ▼
                                                      dead-letter queue (alarm)
```
* **Why asynchronous:** the payment must succeed even if email is down; spikes are absorbed by the queue; each hop can retry on its own.
* **SQS:** long polling, encrypted, redrive policy sends poison messages to the DLQ after 3 tries. **Only producers may send; only the notification worker may receive** (enforced by IAM, see §5).
* **SNS + Lambda:** SNS fans out; the Lambda calls SES for email (only from one verified sender address) or SNS for SMS. Failures retry twice then go to a failure queue with an alarm. The Lambda is explicitly **denied** publishing to topics (no loops).
* **If it fails:** SQS holds messages up to the retention period; nothing is lost while the worker is down. Alarms: DLQ not empty, oldest message too old ("queue stuck"), Lambda errors.
* **Setup a human must do:** verify the SES sender (click AWS's link), leave the SES sandbox (request production access), and for SMS in India register with DLT.

### 4.7 Secrets Manager and IAM
* **Secrets Manager** holds: the database logins (12), the token signing key pair. Pods read **their own** secrets at startup with their own IAM role. There are no Kubernetes `Secret` objects, so nothing secret sits in etcd or can be listed with `kubectl get secret`. **A secret change takes effect at the next pod restart** (`kubectl rollout restart`).
* **IAM**, three kinds in this project:
  1. **Pod roles (EKS Pod Identity):** one role per service. Example: the fee pod may `sqs:SendMessage` to *one* queue and read *its own* DB login and the public key, nothing else. The Terraform `iam` module **rejects wildcards** in code; tests assert each row.
  2. **GitHub roles (OIDC):** CI proves its identity with a short-lived token GitHub signs; AWS exchanges it for temporary credentials. The *image-push* role trusts only `repo:<owner>/<repo>:environment:registry-push` and can only push to our ECR repos; the *website-deploy* role trusts only `…:environment:frontend-<env>` and can only write one bucket and invalidate one distribution. **There are no AWS access keys in GitHub.**
  3. **Service roles:** EKS cluster, nodes, Lambda, flow logs, each with AWS-managed or minimal policies.
* **Authentication vs authorization vs IAM** (the three are independent): the *application* decides who a user is (JWT login) and what they may see (roles, ownership); *IAM* decides what an AWS identity (a pod, a pipeline) may do in AWS. A valid user token grants no AWS permission, and a pod's role says nothing about which family's records a parent may read.

### 4.8 ECR (container registry)
Stores images as `<account>.dkr.ecr.<region>.amazonaws.com/school/<service>:<git sha>`. Tags are **immutable** (a tag always means one build), images are scanned on push, a lifecycle policy keeps the newest 30 and deletes untagged leftovers after 7 days. Only dev owns the registry; stage/prod accounts are allowed to pull.

### 4.9 What we deliberately did *not* use
| Service | Why not |
|---|---|
| API Gateway | duplicate of the ALB's routing; would add cost/latency without a need (no third-party consumers, no per-client quotas) |
| Cognito | the auth service teaches JWT/RBAC; Cognito (or the company IdP) is the enterprise replacement |
| AWS WAF | **not created yet**: the CloudFront module accepts a web ACL but nothing makes one. Add before real users (rate limiting, bot control) |
| Service mesh | NetworkPolicies give network isolation; mutual TLS between services is a later step |

---

## 5. Network and security layers

A request passes several independent checks. Losing one does not lose the system ("defence in depth").

| Layer | Control | Stops |
|---|---|---|
| Edge | HTTPS only; security headers; (WAF planned) | eavesdropping, downgrade, some browser attacks |
| Load balancer | only CloudFront may connect | bypassing CloudFront to hit the ALB directly |
| Kubernetes network | default-deny NetworkPolicy; each service opens only its own paths | a hacked pod scanning or calling other services |
| Pod | non-root (uid 10001), read-only filesystem, no capabilities, seccomp, **no Kubernetes API token** | a compromised process escalating or touching the cluster |
| Application | JWT verified (RS256, issuer, audience, expiry); role check; ownership in SQL | forged/expired tokens, reading other families' data |
| Database | per-service login with minimal rights; separate migrator login | one service's bug damaging another's data or the schema |
| AWS | per-service IAM role, no wildcards; secrets read at startup | one stolen pod reading all secrets or the queue |
| Supply chain | immutable tags, image scan (Trivy), dependency audit, SHA-pinned actions, SBOM, secret scan | vulnerable or tampered builds |
| Pipeline | OIDC (no stored keys), environment-scoped roles, protected `main`, prod approval | a leaked token deploying to prod |

---

## 6. Terraform (infrastructure as code)

### 6.1 The mental model
Terraform reads `.tf` files (what you **want**), compares with the **state** (what it believes exists), asks AWS (what **does** exist), and computes a **plan** (the difference). `apply` makes the plan happen.
```
.tf files (desired) ──┐
state (last known)  ──┼──▶ terraform plan ──▶ terraform apply ──▶ AWS
real AWS (actual)   ──┘
```
* **State** lives in an S3 bucket (one per account), encrypted, with native lock files (`use_lockfile = true`, Terraform 1.10+; no DynamoDB table needed). It is the most sensitive file in the project: never edit by hand, never commit.
* **Backend** = where state is stored. `backend.tf` has the fixed parts; the bucket name comes from `backend.hcl` at `terraform init -backend-config=backend.hcl` (backend blocks cannot use variables).

### 6.2 Layout
`terraform/modules/*` are reusable parts with inputs (`variables.tf`), resources (`main.tf`), outputs (`outputs.tf`) and tests (`tests/*.tftest.hcl`). `terraform/environments/{dev,stage,prod}` contain the **same** `.tf` files (a CI check fails if they drift) and differ only in `terraform.tfvars` and `backend.*`. Names follow `<project>-<env>-<what>`, e.g. `school-prod-vpc`.

### 6.3 Concepts, each with a real example in this repo
| Concept | Example here |
|---|---|
| `variable` / `locals` / `output` | `var.environment`; `local.name_prefix = "school-dev"`; `output "eks_cluster_name"` |
| `count` (on/off) | `module "ecr" { count = var.manage_ecr ? 1 : 0 }`: only dev owns the registry |
| `for_each` (many) | one ECR repository per service: `for_each = local.repo_names` |
| `depends_on` | the EKS cluster waits for its log group so retention is set before logging starts |
| `lifecycle` | `create_before_destroy` on the ALB security group so replacing it never leaves the ALB unprotected |
| validation / `precondition` | prod must be Multi-AZ; `api_origin_protocol = "http"` allowed only in dev (`terraform_data.guardrails`) |
| `moved` block | rename a resource in code without destroying it; add `moved { from = ...; to = ... }` |
| `import` | adopt a resource that already exists in AWS instead of failing with "already exists" |
| tests with mocked AWS | `terraform test` runs every module's and every environment's tests against a fake provider: no account needed |
| ephemeral / write-only | database passwords never reach state (ADR 0006) |

### 6.4 Everyday workflow
```bash
cd terraform/environments/dev
terraform init -backend-config=backend.hcl          # once, and after changing modules/providers
terraform fmt -recursive                            # format
terraform validate                                  # syntax and types
terraform plan  -var-file=terraform.tfvars -out=dev.tfplan   # READ THE PLAN. Look for "destroy" and "replace"
terraform apply dev.tfplan                          # applies exactly what you reviewed
terraform state list                                # what Terraform manages
terraform state show module.rds.aws_db_instance.this
terraform output                                    # values other tools need
terraform import <address> <aws-id>                 # adopt an existing resource
terraform force-unlock <LOCK_ID>                    # only if a crashed run left a lock (be sure nobody is applying)
```
Everything that can be checked **without** AWS: `scripts/tf/check.sh` (format, drift between environments, provider lock consistency, validation, all tests). CI runs it on every change.

### 6.5 Guardrails (the code refuses unsafe settings)
Account check (`allowed_account_ids`: you cannot apply dev's settings to prod's account); prod must have flow logs, Multi-AZ, deletion protection, final snapshot, ≥7 days backups, ≥2 nodes, no force-destroy bucket; no `0.0.0.0/0` for the Kubernetes API; IAM roles may not contain wildcards; stage/prod must encrypt CloudFront→ALB.

### 6.6 Two things Terraform cannot do for you (by design)
1. The **token signing key** is generated outside Terraform (`scripts/aws/put-jwt-key.sh`): a private key must not pass through the state file.
2. Things inside the cluster (Helm/Argo).

---

## 7. Containers

* **One Dockerfile for all six services** (`docker/python-service.Dockerfile`), multi-stage: `builder` installs pinned dependencies → `test` stage runs pytest (the build **fails** if tests fail, on the production Python version) → `runtime` copies only the app, runs as uid 10001, no tests, no dev tools, healthcheck built in.
* Same image, three commands: `uvicorn app.asgi:app` (API), `python -m app.worker` (notification worker), `alembic upgrade head` (migration job).
* Built for **linux/amd64** (our nodes are x86; an image built on an Apple Silicon laptop would not start: the error is `exec format error`).
* **Tag = Git commit SHA.** `latest` is refused by the Helm schema. Given a running pod you can find the exact commit.

```bash
docker build -f docker/python-service.Dockerfile --platform linux/amd64 -t school/fee:dev services/fee
docker build -f docker/python-service.Dockerfile --target test services/fee      # run its tests in the image
docker run --rm school/fee:dev id                                                # uid=10001
aws ecr get-login-password --region ap-south-1 | docker login --username AWS --password-stdin <acct>.dkr.ecr.ap-south-1.amazonaws.com
docker tag school/fee:dev <acct>.dkr.ecr.ap-south-1.amazonaws.com/school/fee:<sha>
docker push <acct>.dkr.ecr.ap-south-1.amazonaws.com/school/fee:<sha>             # normally CI does this, never a person
```

---

## 8. Kubernetes and Helm

### 8.1 Objects you will meet
| Object | Plain meaning | Ours |
|---|---|---|
| Pod | one running copy of a container | a `fee` pod |
| Deployment | "keep N pods of this running; replace them gradually on update" | `fee`, plus `notification-worker` |
| Service | stable internal address + load balancing over pods | `http://fee` inside the cluster |
| Ingress | rules for external traffic (becomes the ALB) | path → service |
| ConfigMap | non-secret settings as env vars | log level, URLs, ARNs |
| ServiceAccount | the pod's identity (linked to its IAM role by Pod Identity) | one per service, named after it |
| HPA | adds/removes pods by CPU | prod only (3-8 pods) |
| PodDisruptionBudget | "never take down too many at once" during node upgrades | min 1 available |
| NetworkPolicy | firewall between pods | default deny + explicit allows |
| Job / CronJob | run-to-completion task / on a schedule | DB bootstrap, migrations, overdue-fee reminders |
| Namespace | a folder that separates environments' objects | `school-dev` |

### 8.2 Helm
Helm is a templating tool: **chart** (templates) + **values** (inputs) = Kubernetes YAML. We have two charts:
* `school-service`: one release per service (six releases). One chart for all six, because six copies would drift.
* `school-platform`: once per namespace (default-deny policy, db-migrator service account, DB bootstrap job).

**Values layers, last wins:** `chart defaults` → `helm/services/<svc>.yaml` (what the service is) → `helm/environments/<env>/common.yaml` (generated from Terraform) → `helm/environments/<env>/<svc>.yaml` (image tag, replicas, autoscaling).

A strict JSON schema (`values.schema.json`) rejects typos and `latest`. `scripts/helm/check.sh` lints, renders all 6 services × 3 environments, validates against Kubernetes 1.34 schemas with `kubeconform`, and runs 161 property tests (every pod hardened, each service gets only its own secrets, routes correct, contracts with Terraform).

```bash
helm lint helm/school-service -f helm/services/fee.yaml -f helm/environments/dev/common.yaml -f helm/environments/dev/fee.yaml
helm template fee helm/school-service -n school-dev -f ... | less           # see the YAML that would be applied
helm list -n school-dev                                                     # what is installed (when installed by hand)
helm rollback fee 3 -n school-dev                                           # only if installed by hand; with Argo CD roll back through Git
```

### 8.3 Pod startup, in order
1. (Before the new version) **migration Job** (Helm hook = Argo PreSync) runs `alembic upgrade head` with the *migrator* login. If it fails the deploy stops; the old version keeps running.
2. Pod starts; reads its secrets from Secrets Manager using its Pod Identity role.
3. `startupProbe`/`readinessProbe` call `/ready` (checks the database). Not ready → no traffic.
4. `livenessProbe` calls `/health` (never touches the database, so a database outage does not make Kubernetes restart healthy pods).
5. On stop, pods wait 10 seconds so the load balancer stops sending traffic before they exit.

---

## 9. CI: from commit to image

### 9.1 The workflows
| Workflow | Runs when | Does |
|---|---|---|
| `ci.yml` | every PR and push to main | figures out *what changed*; for services: ruff, pytest + coverage floor 85%, tests again on **real PostgreSQL**, tests **inside the Docker build**, image checks (non-root, no tests/dev tools shipped), Trivy scan; frontend tests + build; Terraform check; Helm check; lambda and tool tests; actionlint; gitleaks. A final job **`ci-gate`** summarises: it is the only check branch protection needs |
| `sonarqube.yml` | PR and main | all coverage reports → SonarQube analysis → **quality gate** (new code: ≥80% coverage, no new issues, hotspots reviewed, ≤3% duplication) |
| `security.yml` | weekly + when dependencies change | pip-audit, npm audit, Trivy config scan (new CVEs appear without any code change) |
| `build-images.yml` | push to main (changed images only) | tests in build → build linux/amd64 → Trivy scan of **the exact image** → push to ECR by commit SHA → SBOM → record digest. Skips if that SHA already exists (re-runs are safe) |
| `update-deployment.yml` | after a successful image build; or manually | dev: bot commits the new tags into `helm/environments/dev/*.yaml`. stage/prod: opens a pull request copying tags from the previous environment |
| `deploy-frontend.yml` | manual | builds the bundle at a commit, syncs to S3 with the right cache headers, invalidates CloudFront |
| `publish-artifacts.yml` | push to main | frontend bundle + Helm packages → JFrog with build info |

Security features of the pipelines themselves: every third-party action pinned to a **commit SHA**; default permission `contents: read`; `id-token: write` only in jobs that need AWS; no AWS or JFrog keys (OIDC); values from GitHub events go through environment variables, never pasted into shell (prevents script injection); concurrency groups prevent two pushes to the same target.

### 9.2 Who is responsible for what
| Tool | Question it answers |
|---|---|
| GitHub | Where is the code, who reviewed it? |
| GitHub Actions | Run the steps, automatically |
| ruff / pytest / vitest | Is the style right? Does it behave? |
| SonarQube | Is *our* code buggy, insecure, hard to maintain, under-tested? |
| Trivy / pip-audit / npm audit | Do the image or our *dependencies* have known vulnerabilities? |
| gitleaks | Did someone commit a secret? |
| Amazon ECR | Where do runnable images live? |
| JFrog Artifactory | Where do other build outputs live, and (optionally) a cache of PyPI/npm? |
| Argo CD | Make the cluster match Git |

### 9.3 JFrog vs ECR, and why images are not in JFrog
ECR is the cluster's native registry: pulls use the node's IAM role over AWS's network. Making pods depend on an external registry adds a failure point and credentials. JFrog is for **everything else** (many artifact types, promotion, build info, dependency proxy). If a company mandates one registry, ECR becomes a replica of JFrog; that is a documented future change (ADR 0011).

### 9.4 Commands
```bash
python3 scripts/ci/changed.py --base origin/main --head HEAD     # what would CI run for my branch?
scripts/e2e/dry-run.sh                                           # everything CI can check, locally
gh run list --workflow ci.yml --limit 5                          # recent runs
gh run view <id> --log-failed                                    # why did it fail?
```

---

## 10. CD: GitOps with Argo CD

### 10.1 Why not `kubectl` in GitHub Actions?
| Push (pipeline runs kubectl) | Pull (Argo CD, our choice) |
|---|---|
| GitHub needs cluster credentials | GitHub has **no** access to the cluster |
| Cluster API must be reachable from the internet | API can stay private |
| Manual changes go unnoticed | Drift is shown as `OutOfSync`; in dev/stage it is reverted (`selfHeal`) |
| Rollback = rerun an old pipeline | Rollback = `git revert` |

### 10.2 How it is organised
* One Argo CD **inside each environment's cluster** (blast radius; matches one account per environment).
* "App of apps": per environment one **root Application** watches `argocd/envs/<env>/apps/` and creates seven child Applications: `platform` (wave 0), `auth` and `student` (wave 1), then `admission`, `fee`, `attendance`, `notification` (wave 2). A wave starts only when the previous is **Healthy**, so the database roles exist before any service migrates.
* Each Application has two sources: the chart (`helm/school-service`) and the values (`$values/helm/...`), so the values can later live in a separate repository.
* An **AppProject** per environment: only this repository, only namespace `school-<env>`, only namespaced objects (no ClusterRoles, no CRDs).
* The Application files are **generated** by `scripts/argocd/render_apps.py`; CI fails if the committed files differ.

| | dev | stage | prod |
|---|---|---|---|
| Sync | automatic + prune + self-heal | same | **manual** |
| How a new tag arrives | bot commit | reviewed PR | reviewed PR, then press Sync |
| Deleting the Application deletes the workload | yes | yes | **no** (no finalizer) |

### 10.3 What happens on a sync
1. Argo CD (polls every ~3 min) sees a new commit; renders the chart with the values (`helm template`).
2. Compares with the cluster; shows the diff.
3. **PreSync:** runs the migration Job. Failure = stop.
4. Applies changed objects (rolling update of the Deployment).
5. **PostSync:** database bootstrap job (platform app).
6. Waits until health checks pass; marks `Synced / Healthy`.

### 10.4 Rollback
| Situation | Do |
|---|---|
| Normal | `git revert <the deploy commit>` and merge. Argo CD rolls back with the same checks as any deploy |
| Prod emergency (manual sync) | `argocd app rollback school-prod-fee <history id>` **then** revert in Git straight away, or the next sync redeploys the bad version |
| Pods only, quick | `kubectl -n school-prod rollout undo deploy/fee` (a stopgap; Git must be fixed too) |

Database migrations are *not* undone by a rollback. They are written "expand, then contract": the previous code version still works with the new schema.

### 10.5 Commands
```bash
kubectl -n argocd get applications
argocd app get school-dev-fee           # health, sync, running image, recent events
argocd app diff school-dev-fee          # Git vs cluster
argocd app sync school-prod-fee         # the prod "go" button
argocd app history school-prod-fee
```

---

## 11. Deployment strategy

| Concern | What we do | Why |
|---|---|---|
| Update method | **Rolling update**, `maxUnavailable: 0`: a new pod must be Ready before an old one is removed; pods spread across zones | zero downtime without extra infrastructure |
| Database changes | Run **before** the new version, as a Job; "expand, then contract" migrations | old and new pods overlap during a rollout and must both work |
| Safety during node maintenance | PodDisruptionBudget | never lose all replicas of a service at once |
| Traffic drain | 10-second pre-stop wait | the load balancer stops sending requests first |
| Same bytes everywhere | build once, promote the tag | what you tested is what you ship |
| Human gate | stage/prod via pull request; prod needs a manual Sync | accountability and timing control |
| Frontend | immutable fingerprinted assets + no-cache `index.html` + invalidation | users never see a half-updated site |
| Rollback | Git revert | fast and auditable |
| **Not used (yet)** | blue/green and canary releases | rolling is enough for six small services; add **Argo Rollouts** for canary + automatic analysis when traffic or risk grows |

Release flow summary: merge → image → dev (automatic) → verify (smoke test) → PR to stage (automatic) → verify → PR to prod → approve → press Sync → verify.

---

## 12. Observability

### What exists today
| Signal | Where | Notes |
|---|---|---|
| Application logs | stdout of each pod as **JSON** (`timestamp, level, service, environment, request_id, message`) | read with `kubectl logs`; **shipping pod logs to CloudWatch is not set up yet** (planned in Phase 21: a log agent add-on + Logs Insights queries) |
| Kubernetes control-plane logs | CloudWatch Logs (api, audit, authenticator, controllerManager, scheduler) | answers "who changed what in the cluster" |
| RDS PostgreSQL log, Lambda logs, VPC flow logs (prod) | CloudWatch Logs | |
| Health | `GET /health` (liveness), `GET /ready` (readiness; checks the DB) | used by Kubernetes and the ALB |
| Correlation | `X-Request-ID` created at the edge/browser, echoed in responses, in every log line, forwarded to other services; worker uses the event id | one id finds the whole story |
| Alarms (CloudWatch → SNS alerts topic → email) | DLQ not empty · queue messages too old · RDS CPU · RDS free storage · RDS connections · Lambda errors | add `alert_emails` in tfvars and confirm the subscription |
| Metrics | AWS service metrics in CloudWatch; Kubernetes via `kubectl top` (metrics-server) | application metrics (Prometheus/Grafana) are a later step |

### Troubleshooting a failing request: follow the path
`Browser → CloudFront → ALB → Service → Pod → App → Database`. Find the first hop that does not behave.
1. Browser dev tools: the status and the `X-Request-ID` of the failing call.
2. Status 403/502/504 with a CloudFront error page = CloudFront↔ALB problem. A JSON error body with `request_id` = it reached the app.
3. `kubectl -n school-dev logs deploy/fee --since=15m | grep <request_id>`; follow the same id into `student` etc.
4. `kubectl get pods`, `describe pod`: is it Ready?
5. `/ready` failing = database or secret problem.

---

## 13. Troubleshooting by layer (16 scenarios)

Format: **symptom → check → likely cause → fix → verify.** (Phase 21 turns these into step-by-step runbooks in `docs/runbooks/`.)

| # | Symptom | Check | Cause | Fix / verify |
|---|---|---|---|---|
| 1 | Pod `CrashLoopBackOff` | `kubectl -n school-dev logs <pod> --previous`; `describe pod` | bad config, missing secret (`AccessDenied`), DB unreachable, app exception at startup | fix the cause shown in the log; `kubectl rollout status deploy/fee` |
| 2 | `ImagePullBackOff` | `kubectl describe pod` → Events | tag not in ECR (bump ran before build finished or build failed); no pull permission; wrong architecture (`exec format error`) | `aws ecr describe-images --repository-name school/fee --image-ids imageTag=<sha>`; rebuild via CI (amd64) |
| 3 | ECR login fails in CI (`no basic auth credentials`, `Not authorized to perform sts:AssumeRoleWithWebIdentity`) | job log; compare token subject with `terraform output` `subject` | job not in the `registry-push` environment, not on `main`, wrong repo name in tfvars, wrong role ARN variable | fix the variable/environment; re-run |
| 4 | Terraform `Error acquiring the state lock` | message shows lock id and who | a run is in progress or crashed | wait; if sure nobody runs: `terraform force-unlock <id>` |
| 5 | Terraform `already exists` | the error names the resource | created by hand or by a half-failed run | `terraform import <address> <id>` or delete the stray resource; plan shows no diff |
| 6 | Events not turning into notifications | `aws sqs get-queue-attributes ... ApproximateNumberOfMessages`; worker logs; outbox table | worker down, IAM missing `ReceiveMessage`, queue URL wrong, poison message (in DLQ) | restart worker; fix IAM/URL; inspect DLQ message; verify count drops to 0 |
| 7 | Lambda failing (notifications "FAILED") | CloudWatch log group `/aws/lambda/school-<env>-notification-delivery`; failure queue | SES sender not verified / sandbox, bad phone format, DLT not registered | verify sender, request SES production access |
| 8 | `/ready` 503 / DB errors | `kubectl logs`; `aws rds describe-db-instances`; security group rule from cluster | DB down, wrong host in secret, SG rule missing, too many connections | fix SG/secret; pods recover on their own |
| 9 | `could not read secret ... AccessDeniedException` | `aws eks list-pod-identity-associations --cluster-name school-dev` | service account name/namespace differs from the association; secret ARN wrong | names must match exactly (service = service account; namespace `school-<env>`) |
| 10 | ALB targets unhealthy | target group health in console; `kubectl describe networkpolicy`; `/ready` of the pod | readiness failing; NetworkPolicy blocks the VPC range; port mismatch | fix readiness cause; allow VPC CIDR on 8000 |
| 11 | CloudFront returns 502/504 on `/api/*` | `curl -v https://<cf>/api/v1/auth/login`; check origin protocol | origin name/protocol mismatch (https-only to an HTTP listener), ALB SG not allowing CloudFront, ALB not created yet | `scripts/e2e/set-api-origin.sh`; apply; wait ~5 min for CloudFront |
| 12 | Website shows old version or 403 from S3 | `aws s3 ls s3://<bucket>/`; CloudFront invalidations | index.html cached, bucket empty, OAC policy missing | rerun *Deploy frontend*; invalidate `/index.html` |
| 13 | Argo CD `OutOfSync` | `argocd app diff <app>` | manual cluster change, or a field the cluster fills (add to `ignoreDifferences`), or bad values path | revert the manual change or commit it to Git; `render_apps.py --check` |
| 14 | Actions failure | `gh run view --log-failed` | tests/lint/coverage, Trivy finding, OIDC trust, expired token | read the failing step; fix and push |
| 15 | SonarQube gate failed | PR's SonarQube page → new code | coverage <80% on new code, new issue, hotspot unreviewed | add tests / fix issue / review hotspot |
| 16 | JFrog upload/download fails | `jf rt ping`; OIDC claim mapping | wrong URL, OIDC integration claims, missing permission, wrong path/SHA | fix mapping; `jf rt search` for real path |

Generic first aid:
```bash
kubectl -n school-dev get pods,svc,ingress
kubectl -n school-dev describe pod <pod>
kubectl -n school-dev logs deploy/<svc> --tail=100
kubectl -n school-dev get events --sort-by=.lastTimestamp | tail -20
kubectl -n school-dev rollout status deploy/<svc>
kubectl -n school-dev rollout restart deploy/<svc>            # re-read secrets, restart pods gradually
aws sts get-caller-identity                                    # who am I to AWS?
```

---

## 14. Day-to-day operations

| Task | How |
|---|---|
| Deploy a code change | merge a PR. That is all (dev). Promote through the workflow |
| Release to prod | run *Update deployment configuration* (stage → prod), review and merge the PR, press Sync in Argo CD, run `scripts/e2e/smoke.py` against prod's URL with a **test** account only if allowed (it creates records) |
| Rotate a database password | bump `credentials_version` in Terraform, apply, then `kubectl rollout restart` the service |
| Rotate the signing key | `scripts/aws/put-jwt-key.sh <env> --rotate` (all tokens stop working), restart auth and all services |
| Create a user | admin in the portal (`/users`); first admin: `python -m app.cli create-admin` via `kubectl exec` |
| Upgrade Kubernetes | change `kubernetes_version` one minor version at a time, apply, then nodes roll; check add-on versions first |
| Upgrade a dependency | Dependabot PRs weekly; CI proves them |
| Add an alert email | `alert_emails` in tfvars, apply, click the AWS confirmation link |
| Scale | change `replicaCount` / autoscaling values in `helm/environments/<env>/<svc>.yaml` and node sizes in tfvars |
| Look at what changed in prod | `git log -- helm/environments/prod` |
| Stop paying for dev | see the tear-down section of [deployment.md](deployment.md) (delete the root application first, then `terraform destroy`) |

## 15. Cost, backup, disaster recovery

* **Rough dev cost** (see `docs/terraform.md`): EKS control plane ≈ USD 73, 2 small nodes ≈ 60, NAT ≈ 35-45, RDS micro ≈ 15-20, ALB ≈ 20, small items (Secrets Manager ≈ 0.40 per secret, CloudFront, SQS...). **≈ USD 200-250/month if left on.** Destroy dev when idle. Prod is several times more (3 NATs, Multi-AZ, bigger nodes).
* **Backups:** RDS automated backups (dev 1 day, stage 7, prod 14) with point-in-time restore; prod takes a final snapshot on deletion and has deletion protection. Terraform state bucket is versioned. Git holds everything else. Secrets can be recovered within the recovery window (prod 30 days).
* **Rebuild from scratch:** infrastructure = `terraform apply`; software = Argo CD sync from Git; data = restore the RDS snapshot. **A full restore drill has not been done**: schedule one before real users.
* **Not covered yet:** cross-region replicas, a documented RTO/RPO, chaos testing.

## 16. Decisions, trade-offs, and what an enterprise would add

The `docs/adr/` folder records each decision with its reason and "revisit when". Highlights:

| Our choice (learning-friendly) | Enterprise alternative |
|---|---|
| One RDS instance, one schema per service | one database per service (or Aurora per domain) |
| Own auth service + JWT | Cognito / corporate IdP (OIDC, SSO, MFA) |
| One repository | multi-repo with a platform team owning shared charts/modules |
| Values and chart in the same repository | separate GitOps repository with its own approvers |
| `kubectl logs` for pod logs (today) | CloudWatch Container Insights or an ELK/Loki stack; Prometheus + Grafana; tracing (OpenTelemetry/X-Ray) |
| Rolling updates | canary/blue-green with automated analysis (Argo Rollouts) |
| Self-managed SonarQube trial | SonarQube Cloud or a hosted enterprise instance |
| AWS-managed encryption keys | customer-managed KMS keys with key policies |
| No WAF | AWS WAF with managed rule sets and rate limits in front of CloudFront |
| Single region | multi-region DR plan |
| Manual secret rotation | automatic rotation, External Secrets/CSI driver |
| Policy by tests | policy-as-code (OPA/Kyverno admission policies) |

**Known gaps in this repository today** (honest list): not yet deployed to a real AWS account (the dry run proves everything that can be proven offline); pod log shipping and dashboards (Phase 21); no WAF; Docker image builds could not be exercised on the author's machine during the dry run (the CI does it); routing tables for the local environments (Vite, nginx) are synchronised by hand with Helm's; a restore drill has not been run.

## 17. Command cheat sheet

```bash
# identity
aws sts get-caller-identity
aws eks update-kubeconfig --name school-dev --region ap-south-1
# terraform
terraform init -backend-config=backend.hcl | validate | plan -out=x | apply x | state list | state show <addr> | output | import <addr> <id>
# docker
docker build -f docker/python-service.Dockerfile -t school/fee:dev services/fee ; docker run --rm school/fee:dev id ; docker tag ... ; docker push ...
# kubernetes
kubectl get pods,svc,ingress -n school-dev | describe pod <p> | logs deploy/<svc> --tail=100 | rollout status|restart|undo deploy/<svc> | top pods
kubectl -n school-dev exec -it deploy/fee -- id
# helm
helm lint ... | template ... | list -n school-dev | rollback <release> <rev> -n school-dev
# argo cd
argocd app list | get <app> | diff <app> | sync <app> | history <app> | rollback <app> <id>
# git
git clone | checkout -b | pull --rebase | merge | tag v1.0.0 | revert <sha>
# ecr
aws ecr describe-images --repository-name school/fee ; aws ecr get-login-password | docker login ...
# s3 / cloudfront
aws s3 ls s3://<bucket>/ ; aws cloudfront create-invalidation --distribution-id <id> --paths "/index.html"
# queues
aws sqs get-queue-attributes --queue-url <url> --attribute-names All
# repo helpers
scripts/e2e/dry-run.sh [--with-stack] | scripts/e2e/preflight.py --env dev --phase pre-apply | scripts/e2e/configure.py --help
scripts/e2e/native-stack.sh start|stop | scripts/e2e/smoke.py <url> | scripts/e2e/set-api-origin.sh dev
```

## 18. Glossary
| Term | Meaning |
|---|---|
| AZ (availability zone) | one data center (or group) inside an AWS region; spread across several to survive failure |
| Argo CD | tool inside the cluster that makes the cluster match Git |
| CDN / CloudFront | network of caches near users |
| CI / CD | continuous integration (build+test on every change) / continuous delivery (get it running) |
| Container / image | a packaged program with its dependencies / the recipe it runs from |
| ECR | AWS container registry |
| EKS | AWS managed Kubernetes |
| GitOps | Git is the source of truth for what runs; a robot applies it |
| Helm / chart / values | Kubernetes templating / the templates / the inputs |
| IAM role | an AWS identity with permissions that can be assumed temporarily |
| Ingress / ALB | Kubernetes external routing rule / AWS load balancer built from it |
| NAT gateway | lets private machines reach the internet outward only |
| OIDC | a way for GitHub to prove its identity to AWS without stored keys |
| Outbox | table of "events to send" written in the same transaction as the data |
| Pod / Deployment | running copy of a container / controller keeping N pods running |
| RDS | AWS managed relational database |
| SBOM | list of every component inside an image |
| Security group | AWS virtual firewall around a resource |
| Terraform state | Terraform's record of what it created |
| VPC / subnet | your private network in AWS / a slice of it |
