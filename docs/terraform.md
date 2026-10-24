# Terraform guide

Everything here is about the code in [terraform/](../terraform/). Run the offline checks any time, with no AWS account:

```bash
scripts/tf/check.sh      # format, validate, environments in step, 54 offline tests
```

## Layout

```
terraform/
├── bootstrap/            creates the state bucket for ONE AWS account (run once per account)
│   └── envs/{dev,stage,prod}.tfvars
├── modules/
│   ├── vpc/              network: 3 subnet tiers, NAT modes, routes, endpoints, flow logs          Phase 12
│   ├── ecr/              image registry: lifecycle, immutable tags, cross-account pull              Phase 12
│   ├── rds/              PostgreSQL: private, encrypted, RDS-managed admin password                 Phase 13
│   ├── secrets/          per-service DB logins (kept out of state) + signing-key containers         Phase 13
│   ├── sqs/              event queue + dead-letter queue                                            Phase 13
│   ├── sns/              topics (notifications, alerts) and subscriptions                           Phase 13
│   ├── s3/               private bucket (frontend files)                                            Phase 13
│   ├── cloudfront/       CDN: static site + /api/* routing, security headers, SPA routing           Phase 13
│   ├── iam/              one least-privilege role per service (EKS Pod Identity); rejects wildcards Phase 13
│   ├── lambda/           a function with its role, logs, SNS trigger and failure queue              Phase 13
│   ├── observability/    CloudWatch alarms: dead letters, stuck queue, database, function errors    Phase 13
│   ├── eks/              cluster, nodes, access entries, Pod Identity, load balancer controller role   Phase 14
│   └── github-oidc/      (empty placeholder)                                                           Phase 16
└── environments/
    └── dev|stage|prod/   versions.tf providers.tf variables.tf locals.tf main.tf outputs.tf   (identical in all three)
                          backend.tf  backend.hcl  terraform.tfvars                              (differ per environment)
```

There is deliberately no ALB or API Gateway module: ALB is created by the Kubernetes Ingress controller (Phase 14/15),
and API Gateway is not used (ADR 0001, D2). See [ADR 0006](adr/0006-aws-resources.md) for what changed from the original plan.

## The mental model

```
 your .tf files  ──►  terraform plan  ◄──  state (what Terraform believes exists)
   (what you want)           │                         ▲
                             ▼                         │ updated after every apply
                      the list of changes ──► terraform apply ──► AWS API
```

Terraform never looks at AWS "blind": it compares three things, the code, the state, and (when planning) AWS's actual
answers. A resource in state but not in code is destroyed. In code but not in state is created. Different is changed.

## First-time setup, per environment

```bash
aws sts get-caller-identity                              # which account am I? it must match the tfvars
AWS_PROFILE=school-dev scripts/tf/bootstrap.sh dev plan  # review
AWS_PROFILE=school-dev scripts/tf/bootstrap.sh dev apply # creates the state bucket; prints backend.hcl content
# paste that into terraform/environments/dev/backend.hcl, then:
cd terraform/environments/dev
terraform init -backend-config=backend.hcl
terraform plan -out=plan.tfplan
terraform apply plan.tfplan
```

Before the first plan, replace the placeholder account ids (`111111111111` and friends) in `bootstrap/envs/*.tfvars` and
`environments/*/terraform.tfvars` with your real ones.

## After the first apply: the steps no automation can do for you

```bash
# 1. The token signing key (Terraform creates only the empty secrets; it must never see the key)
AWS_PROFILE=school-dev scripts/aws/put-jwt-key.sh dev

# 2. Alarm emails: put addresses in terraform.tfvars (alert_emails), apply, then each person clicks the AWS confirmation link.
#    Notification emails: set ses_from_address, apply, then click the confirmation link AWS emails to that address.
#    A new account's SES is in "sandbox" mode (verified recipients only): request production access in the SES console.

# 3. The database logins (schemas, roles and their passwords) are created inside the cluster by the bootstrap job in Phase 15,
#    using the secrets Terraform wrote. Until then the database exists but is empty and unreachable (its firewall has no rules).

# 4. Deploy the frontend
cd frontend && npm ci && npm run build
BUCKET=$(terraform -chdir=../terraform/environments/dev output -raw frontend_bucket)
# hashed assets can be cached for a year; index.html must NEVER be cached, or users see an old version after a deploy
aws s3 sync dist/ "s3://$BUCKET/" --delete --exclude index.html --cache-control "public,max-age=31536000,immutable"
aws s3 cp dist/index.html "s3://$BUCKET/index.html" --cache-control "no-cache"
aws cloudfront create-invalidation --distribution-id "$(terraform -chdir=../terraform/environments/dev output -raw cloudfront_distribution_id)" --paths "/index.html"
```

## Using the cluster (after the apply)

```bash
terraform output kubeconfig_command                       # prints the command below
aws eks update-kubeconfig --name school-dev --region ap-south-1
kubectl get nodes                                         # 2 nodes, STATUS Ready, in your private subnets
kubectl -n kube-system get pods                           # coredns, kube-proxy, aws-node, eks-pod-identity-agent: Running
aws eks list-pod-identity-associations --cluster-name school-dev    # 8 entries: 7 roles + the load balancer controller
```

Your IAM role must be in `eks_admin_principal_arns` and your current address in `eks_public_access_cidrs`, or kubectl is
refused. **Check what your address is, then edit `terraform.tfvars`; the committed `203.0.113.7/32` is a documentation placeholder.**

What Terraform deliberately does NOT do: install anything inside the cluster. The next phases do that with Helm and Argo CD:
the AWS Load Balancer Controller (service account `aws-load-balancer-controller` in `kube-system`, already linked to its role),
metrics-server (needed by the autoscaler), and our services (each in namespace `school-<env>`, with a service account named after
the service).

## Secrets: what is and is not in the state file

| Secret | How it is created | In Terraform state? |
|---|---|---|
| Database administrator password | RDS generates and rotates it (`manage_master_user_password`) | **No** |
| Per-service database passwords | Ephemeral `random_password`, written to Secrets Manager through a write-only argument | **No** |
| Token signing key | `scripts/aws/put-jwt-key.sh` (outside Terraform) | **No** |
| Secret *names*, ARNs, database host name | Ordinary resources | Yes (not sensitive) |

Rotate the service passwords by increasing `credentials_version` in the secrets module call and applying; then re-run the
database bootstrap job so PostgreSQL learns the new passwords.

## Concepts, each with the real example

**State.** A JSON file mapping each resource in the code to the real thing in AWS (its id, its attributes). It can
contain secrets (passwords Terraform generated), so it is stored encrypted in S3, never in Git.
`terraform state list` shows what is tracked; `terraform state show module.vpc.aws_vpc.this` shows one entry.

**Backend.** Where state lives. `environments/dev/backend.tf` says S3, key `school/dev/platform.tfstate`.
`use_lockfile = true` writes a lock object beside the state so two people (or two pipelines) cannot apply at once.
The bucket name is not in the file because backend blocks cannot use variables: it comes from `backend.hcl` at init.
Versioning on the bucket means a bad state file can be rolled back.

**Why `bootstrap` uses local state.** The state bucket cannot be created by a configuration that keeps its state in
that same bucket. So this one small configuration keeps a local file (`bootstrap/state/<env>.tfstate`, git-ignored).

**Modules.** A folder of Terraform you call like a function. `main.tf` in each environment calls `../../modules/vpc` with
inputs (`cidr_block`, `azs`, `nat_mode`) and reads outputs (`module.vpc.private_subnet_ids`). The same module builds
dev, stage and prod; only the inputs differ.

**Variables, tfvars.** `variables.tf` declares inputs with types, descriptions and `validation` blocks
(for example `cidr_block` must end in `/16`). Values come from `terraform.tfvars` (committed, not secret),
`-var name=value`, or `TF_VAR_name` environment variables. Secrets never go in tfvars.

**Locals.** Named expressions computed once: `local.name_prefix = "${var.project}-${var.environment}"`; the subnet address plan
in the VPC module. Use them to avoid repeating a formula.

**Outputs.** What a configuration exposes: `module.vpc.vpc_id`, `private_subnet_ids`, `nat_public_ips`. Phase 13 and 14
modules take these as inputs.

**`count` vs `for_each`.**
- `count = var.manage_ecr ? 1 : 0` (environment `main.tf`) makes a whole module optional: 0 or 1 copies. Also used for optional single resources (VPC flow logs).
- `for_each` creates one per item and keys them by name: subnets are `aws_subnet.private["ap-south-1a"]`.
  With `count` they would be `[0]`, `[1]`; removing the first zone would renumber the rest, and Terraform would destroy and recreate them. With `for_each`, removing a zone removes only that zone.

**`depends_on`.** Terraform normally learns the order from references (a subnet refers to the VPC). The NAT gateway does not
refer to the internet gateway but needs it attached first, so `depends_on = [aws_internet_gateway.this]` says so.
The environment's `module.vpc` depends on `terraform_data.guardrails` so nothing is built until the rules pass.

**`lifecycle`.**
| Setting | Where | Meaning |
|---|---|---|
| `prevent_destroy` | state bucket | Terraform refuses to delete it |
| `create_before_destroy` | VPC endpoint security group | Build the replacement first, then remove the old (a group in use cannot be deleted) |
| `precondition` | `terraform_data.guardrails` | A rule checked at plan time (prod must use `per_az` NAT) |
| `ignore_changes` | EKS node group (Phase 14) | Do not fight the autoscaler over `desired_size` |

**`moved` blocks.** Renaming a resource in code would normally mean "destroy the old, create a new one". A `moved` block says it
is the same thing:
```hcl
moved {
  from = aws_subnet.private_a
  to   = aws_subnet.private["ap-south-1a"]
}
```
Terraform updates the state during the next apply, with no change in AWS. Unlike `terraform state mv`, it is code: reviewed
in the PR, and it works for every environment automatically. Keep it for a release or two, then delete it.

**Importing existing resources.** Something exists in AWS (created by hand) and should be managed by Terraform. Two ways:
```hcl
# 1. config-driven (preferred; reviewed in a PR):
import {
  to = module.ecr[0].aws_ecr_repository.this["fee"]
  id = "school/fee"
}
```
```bash
terraform plan -generate-config-out=generated.tf   # optional: Terraform drafts the resource block for you
terraform apply                                     # adopts it into state; nothing in AWS changes if the code matches
# 2. command-driven, one at a time:
terraform import 'module.ecr[0].aws_ecr_repository.this["fee"]' school/fee
```
After importing, `terraform plan` must say "no changes". If it shows differences, either fix the code or accept the change.

## Everyday commands

| Command | What it does |
|---|---|
| `terraform init -backend-config=backend.hcl` | Download providers/modules, connect to the state |
| `terraform fmt -recursive` | Format the code |
| `terraform validate` | Check syntax and types (no AWS needed) |
| `terraform test` | Run the offline tests |
| `terraform plan -out=plan.tfplan` | Show what would change and save that exact plan |
| `terraform apply plan.tfplan` | Apply exactly the plan you reviewed |
| `terraform state list` / `state show <addr>` | Inspect what is tracked |
| `terraform output` | Print outputs |
| `terraform force-unlock <id>` | Remove a stuck lock (see below) |
| `terraform destroy` | Delete everything in this environment's state |

Avoid `-target` except for emergencies: it applies part of the configuration and can leave the rest inconsistent.

## Troubleshooting

| Symptom | Likely cause | Check | Fix |
|---|---|---|---|
| `Error acquiring the state lock` | Another run is in progress, or a run was killed and left the lock | The error shows who and when. In S3 look for `…tfstate.tflock` | If nobody is running: `terraform force-unlock <LOCK ID>` |
| `AlreadyExists` / `BucketAlreadyOwnedByYou` / "already exists" on create | The resource exists in AWS but not in state (created by hand, or state lost) | `aws ecr describe-repositories --repository-names school/fee` | `import` it (above), then plan again |
| `Provider produced inconsistent result` or `AccessDenied` | The credentials lack permission | `aws sts get-caller-identity`; the denied action is named in the error | Fix the IAM role; do not widen it to `*` |
| `…not in the list of allowed account ids` | Wrong credentials for this environment | `aws sts get-caller-identity` versus `allowed_account_ids` | Switch profile. This is the safety net working |
| Plan shows a resource will be **replaced** (`-/+`) | A changed attribute cannot be updated in place | The line with `# forces replacement` | Read it carefully before applying; for a database or bucket this can mean data loss |
| Plan wants to change things you did not touch (drift) | Someone changed it in the console | `terraform plan` shows the diff | Decide: re-apply (undo the change) or update the code to match |
| `Failed to query available provider packages` / checksum mismatch | Lock file does not have your platform | `.terraform.lock.hcl` | `terraform providers lock -platform=darwin_arm64 -platform=linux_amd64` |
| `Inconsistent dependency lock file` | Provider constraints changed | | `terraform init -upgrade`, review, commit the lock |
| `Invalid count argument ... depends on resource attributes that cannot be determined until apply` | A `count`/`for_each`/condition depends on an ARN or id of something created in the same run | The error names the line | Decide from something known at plan time (a variable, or whether an object is `null`); see the lambda module's `sns_trigger` |
| Alarm emails never arrive | The subscription is still "Pending confirmation" | `aws sns list-subscriptions-by-topic --topic-arn <alerts topic>` | Click the link AWS emailed |
| `MessageRejected: Email address is not verified` (delivery function logs) | The SES sender is unconfirmed, or the account is in the SES sandbox and the recipient is unverified | `aws sesv2 get-email-identity --email-identity <address>` | Confirm the sender; request SES production access |
| CloudFront shows `AccessDenied` (XML) for a page | The file is not in the bucket, or the bucket policy does not name this distribution | `aws s3 ls s3://<bucket>/`; check the distribution id in the bucket policy | Upload the build; re-apply |
| Reloading `/payments` returns an error | The SPA routing function is missing or not attached | `aws cloudfront get-distribution-config` | Re-apply the cdn module |
| API calls return the HTML page instead of JSON | The `/api/*` behavior is missing (no `api_origin_domain_name` yet) | Plan output of the cdn module | Set `api_origin_domain_name` after the Ingress creates the load balancer |
| `couldn't get current server API group list` / kubectl times out | Your address is not in `eks_public_access_cidrs` (your ISP changed it) | `curl -s https://checkip.amazonaws.com` | Update the list and apply |
| `You must be logged in to the server (Unauthorized)` | Your IAM role has no access entry | `aws eks list-access-entries --cluster-name school-dev` | Add it to `eks_admin_principal_arns` and apply |
| Pods `ImagePullBackOff` with `no match for platform` or `exec format error` | An arm64 image (built on a Mac) on x86_64 nodes | `docker image inspect --format '{{.Architecture}}' <image>` | Deploy only images built by CI (linux/amd64) |
| A pod cannot use its AWS permissions (`AccessDenied`, or the node's role shows in `sts get-caller-identity`) | The service account name or namespace differs from the association | `aws eks list-pod-identity-associations --cluster-name school-dev` | Make the Helm chart use the exact namespace and service account name |
| Nodes `NotReady` right after creation | The CNI add-on is still starting, or the nodes cannot pull images (no route/NAT) | `kubectl describe node`; check the NAT gateway | Wait a few minutes; verify private-subnet routes |
| A guardrail error (for example "prod must use per_az") | `terraform.tfvars` breaks a rule | The message names the rule | Fix the value |

## What it costs (approximate, check the AWS pricing page for your region)

| Item | Per month | Where |
|---|---|---|
| NAT gateway | roughly USD 32-45 each, plus per-GB data | dev 1, stage 1, prod 3 |
| Interface VPC endpoint | roughly USD 7 per zone each | prod: 7 endpoints x 3 zones |
| VPC flow logs | per GB ingested | stage, prod |
| ECR | per GB stored; lifecycle policy keeps it flat | dev only |
| EKS control plane | roughly USD 73 **per cluster**, always on | one per environment |
| Worker nodes | EC2 hours: 2 x t3.medium is roughly USD 60 | dev 1-3, stage 2-4, prod 3-6 (m5.large) |
| RDS (db.t4g.micro dev, .small stage, .medium prod) | instance-hours + storage + backups; **Multi-AZ roughly doubles it** | all (prod Multi-AZ) |
| Secrets Manager | about USD 0.40 per secret per month (14 secrets: 12 logins + 2 key containers) | all |
| CloudFront, S3, SQS, SNS, Lambda, CloudWatch alarms | pay per use; negligible at school scale | all |
| VPC, subnets, route tables, internet gateway, S3 gateway endpoint | free | all |

Destroy dev when you are not using it: `terraform destroy` removes the NAT gateway, which is most of dev's cost.
