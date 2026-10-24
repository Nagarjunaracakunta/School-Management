# Deployment runbook: from an empty AWS account to a working portal

Everything below was rehearsed offline by `scripts/e2e/dry-run.sh` (see the end of this file). What a rehearsal cannot prove is
marked **[first real run]**: watch those steps carefully.

Time: about 3 hours the first time, most of it waiting (EKS and RDS take 15-25 minutes to create).
Cost while running: roughly USD 150-250 per month for dev. **Destroy it when you stop** (last section).

## 0. What you need

| Need | Check |
|---|---|
| An AWS account for dev (stage and prod later) and a role you can assume with administrator rights, preferably through IAM Identity Center (SSO) | `aws sts get-caller-identity --profile school-dev` prints the account id |
| A GitHub account and an empty repository named `school-management` | |
| Tools: git, python3, node 22, terraform 1.15, aws CLI v2, kubectl, helm 4 (docker, gh, argocd are optional) | `scripts/e2e/preflight.py --tools` |
| Your public address | `curl -s https://checkip.amazonaws.com` |

No domain name is needed for dev. Without one, CloudFront reaches the load balancer over HTTP (`api_origin_protocol = "http"`,
dev only). Stage and prod need a domain and a certificate (guardrails enforce it).

## 1. Fill in your values (10 minutes)

```bash
scripts/e2e/configure.py --github-owner <you> --dev-account <12 digits> \
    --my-ip <your public ip> --admin-role-arn arn:aws:iam::<12 digits>:role/<your admin role>
git diff                                                  # read what changed
scripts/e2e/preflight.py --env dev --phase pre-apply      # expected: "no placeholders left"
```
The administrator role is the IAM role you assume (for SSO it looks like `AWSReservedSSO_AdministratorAccess_xxxx`). It becomes
Kubernetes cluster-admin. Do not use a personal IAM user.

## 2. Put the code on GitHub and prepare GitHub (20 minutes)

```bash
git add -A && git commit -m "Initial commit" && git branch -M main
git remote add origin git@github.com:<you>/school-management.git
git push -u origin main        # CI starts; the image build fails until step 5 (no AWS role yet). That is expected.
```
In the repository settings:
1. Environments: create `registry-push` (deployment branches: `main` only) and `frontend-dev`. Later `frontend-stage`, `frontend-prod` (required reviewers).
2. Actions: allow GitHub Actions to create pull requests.
3. Branch protection for `main`: require pull requests and the status check `ci-gate`. Allow the Actions bot to push, or dev tag updates cannot land (docs/argocd.md).

## 3. Terraform state bucket (5 minutes)

```bash
export AWS_PROFILE=school-dev
aws sso login --profile school-dev
scripts/tf/bootstrap.sh dev plan
scripts/tf/bootstrap.sh dev apply        # prints the backend settings: paste them into terraform/environments/dev/backend.hcl
```
Verify: `aws s3 ls | grep tfstate`. Commit `backend.hcl`.

## 4. Create the platform (35 minutes) [first real run]

```bash
cd terraform/environments/dev
terraform init -backend-config=backend.hcl
terraform plan -var-file=terraform.tfvars -out=dev.tfplan     # read it. Only additions on a first run: read the list and count what you expect (network, database, cluster, queues, secrets, bucket, CDN)
terraform apply dev.tfplan
```
Verify:
```bash
terraform output                                          # vpc_id, eks_cluster_name, portal_domain_name, github_*_role_arn ...
aws eks update-kubeconfig --name school-dev --region ap-south-1
kubectl get nodes                                         # 2 nodes Ready
```
Common failures: `AccessDenied` (wrong profile), `You must be logged in to the server` (your role is not in
`eks_admin_principal_arns`, or your address changed), `ResourceAlreadyExists` (a previous partial run: docs/terraform.md).

Then, once per environment, the token signing key (it must never pass through Terraform):
```bash
cd ../../.. && scripts/aws/put-jwt-key.sh dev
```

## 5. Connect GitHub to AWS (10 minutes)

```bash
terraform -chdir=terraform/environments/dev output -raw github_ecr_push_role_arn
terraform -chdir=terraform/environments/dev output -raw github_frontend_deploy_role_arn
terraform -chdir=terraform/environments/dev output -raw frontend_bucket
terraform -chdir=terraform/environments/dev output -raw cloudfront_distribution_id
```
| Where in GitHub | Variable | Value |
|---|---|---|
| Repository variables | `AWS_REGION` | `ap-south-1` |
| Repository variables | `AWS_ECR_PUSH_ROLE_ARN` | first output |
| Environment `frontend-dev` | `AWS_REGION`, `AWS_FRONTEND_DEPLOY_ROLE_ARN`, `FRONTEND_BUCKET`, `CLOUDFRONT_DISTRIBUTION_ID` | region and the other three outputs |

None of these is a secret: they are addresses. There is no AWS access key anywhere (OIDC).

## 6. Build the images (15 minutes) [first real run]

Actions, "Build and push images", Run workflow (images: `all`). It tests, builds (linux/amd64), scans (Trivy) and pushes
`school/<service>:<git sha>` to ECR, then "Update deployment configuration" commits those tags to `helm/environments/dev/*.yaml`.
```bash
aws ecr describe-images --repository-name school/fee --query 'imageDetails[].imageTags'      # the commit sha
git pull                                                                                       # the bot's commit
grep -rn 'tag:' helm/environments/dev/                                                         # real SHAs, no 0000000
```
If Trivy fails the build: upgrade the named package; do not silence it without a reason and an expiry date (`.trivyignore`).

## 7. Generate the Helm values from Terraform (5 minutes)

```bash
terraform -chdir=terraform/environments/dev output -json > /tmp/outputs-dev.json
scripts/helm/render-env-values.py dev /tmp/outputs-dev.json
scripts/e2e/preflight.py --env dev --phase pre-deploy     # expected: no placeholders left
HELM_BIN=helm KUBECONFORM_BIN=kubeconform scripts/helm/check.sh
git add -A && git commit -m "dev: environment values" && git push
```
Argo CD reads from Git, so this must be pushed before step 8.

## 8. Cluster add-ons, then Argo CD (20 minutes) [first real run]

```bash
scripts/helm/install-addons.sh dev          # AWS Load Balancer Controller + metrics-server
scripts/argocd/install.sh dev               # Argo CD, then the project and the root application
kubectl -n argocd get applications -w       # watch: platform first, then auth+student, then the rest
```
Expected end state: seven applications `Synced` and `Healthy`.
```bash
kubectl -n school-dev get pods              # all Running/Ready (the notification worker too)
kubectl -n school-dev get ingress           # an ADDRESS (the load balancer's DNS name) on every row
kubectl -n school-dev logs job/db-bootstrap # "database bootstrap finished"
```
A private repository needs read access for Argo CD first (`argocd repo add ...`, docs/argocd.md).

## 9. Create the first administrator

```bash
read -rs -p "Admin password (12+ chars): " ADMIN_PW; echo
kubectl -n school-dev exec deploy/auth -- env AUTH_ADMIN_PASSWORD="$ADMIN_PW" \
    python -m app.cli create-admin --email admin@yourschool.example --name "School Admin"
```
Use an e-mail address with a real-looking domain (`.local` and `.test` are rejected by the login validation).

## 10. Open the route from CloudFront to the services (10 minutes) [first real run]

CloudFront needs the load balancer's name, which exists only now.
```bash
scripts/e2e/set-api-origin.sh dev                        # reads it from the cluster and writes terraform.tfvars
terraform -chdir=terraform/environments/dev apply -var-file=terraform.tfvars
git add -A && git commit -m "dev: api origin" && git push
```
The CloudFront change takes about 5 minutes to spread.

## 11. Publish the website

Actions, "Deploy frontend", environment `dev`. Or by hand:
```bash
cd frontend && npm ci && npm run build && cd ..
scripts/e2e/deploy-frontend.sh frontend/dist "$(terraform -chdir=terraform/environments/dev output -raw frontend_bucket)" \
    "$(terraform -chdir=terraform/environments/dev output -raw cloudfront_distribution_id)"
```

## 12. Prove it works

```bash
URL="https://$(terraform -chdir=terraform/environments/dev output -raw portal_domain_name)"
curl -sI "$URL" | head -1                                   # HTTP/2 200
SMOKE_EMAIL=admin@yourschool.example SMOKE_PASSWORD="$ADMIN_PW" scripts/e2e/smoke.py "$URL"
```
Expected last line: `PASSED in ...s`. The same script passed against the local stack in 3.7 seconds; against AWS the
"EVENTS" step takes longer because messages travel through SQS and SNS.
Then open the URL in a browser, log in, and click through Dashboard, Admissions, Fees, Attendance, Notifications.

If the smoke test fails, find the layer: docs/devops-guide.md, section "Troubleshooting by layer".

## 13. Stage and prod

Repeat steps 3-11 per environment with its own account (`configure.py --stage-account ...`). Differences:
images are NOT rebuilt (promotion copies dev's tags: Actions, "Update deployment configuration", Run workflow); stage and prod need a
domain, an ACM certificate (CloudFront's in `us-east-1`, the load balancer's in the cluster's region) and `api_origin_protocol = "https"`;
prod Argo CD applications wait for a manual Sync.

## Tear down (do this when you are done with dev)

Order matters: the load balancer is created by Kubernetes, not Terraform, and blocks deleting the network if it still exists.
```bash
kubectl -n argocd delete application school-dev-root          # removes the apps (finalizers), and with them the Ingress and the load balancer
kubectl -n school-dev get ingress                              # wait until: No resources found
aws elbv2 describe-load-balancers --query 'LoadBalancers[].LoadBalancerName'   # none starting with k8s-
terraform -chdir=terraform/environments/dev destroy -var-file=terraform.tfvars
```
Secrets are scheduled for deletion immediately in dev (`secrets_recovery_days = 0`). The state bucket from step 3 is kept on purpose;
remove it by hand only when the account is finished.

## What the dry run proved (and what it could not)

Run `scripts/e2e/dry-run.sh --with-stack` at any time. It checks, with no AWS account:

| Proven offline | Not provable without an account |
|---|---|
| All six services: lint, tests, coverage floor | `terraform apply` really succeeding (quotas, name collisions, permissions) |
| Terraform: formatting, validation, 30+ test runs for every module and environment, guardrails | Images building on the CI runners and being pushed |
| Helm: lint, render, Kubernetes schema validation, 161 property tests for 6 services x 3 environments | Pods starting on real nodes, Pod Identity, network policies on the real CNI |
| Argo CD files equal what the generator makes; every referenced path exists | Argo CD syncing against the real repository |
| Workflow files lint clean; no secrets in the tree | OIDC trust between GitHub and AWS |
| Whole platform running (6 services, queue, worker, portal) and the three business flows + RBAC + request ids passing | CloudFront, ALB, RDS behaviour |
