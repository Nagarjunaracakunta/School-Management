# Helm guide

Two charts, in [helm/](../helm/):

| Chart | Install | Creates |
|---|---|---|
| `school-platform` | once per namespace, FIRST | the `db-migrator` service account, a default-deny network policy, resource defaults, and the **database bootstrap job** |
| `school-service` | once per service (six releases) | Deployment, Service, ConfigMap, ServiceAccount, Ingress, NetworkPolicy, HPA and PodDisruptionBudget (when enabled), the **migration job** (a hook), and for Notification the queue worker; for Fee the overdue-reminder CronJob |

Values come from layers, later wins:  `chart defaults` → `helm/services/<service>.yaml` (what the service IS) →
`helm/environments/<env>/common.yaml` (GENERATED from Terraform) → `helm/environments/<env>/<service>.yaml` (image tag, size).

## Check everything without a cluster

```bash
HELM_BIN=helm KUBECONFORM_BIN=kubeconform scripts/helm/check.sh
```
It lints and renders all 6 services × 3 environments, validates each against the Kubernetes 1.34 API schemas, and runs ~160
property tests (every pod hardened, each service gets only its own secrets, the routes, the contracts with Terraform).

## Generate the environment values after `terraform apply`

```bash
cd terraform/environments/dev && terraform output -json > /tmp/outputs-dev.json && cd -
scripts/helm/render-env-values.py dev /tmp/outputs-dev.json                   # add --certificate-arn arn:aws:acm:... for HTTPS
git diff helm/environments/dev/common.yaml                                     # review, commit
```
The committed `common.yaml` files contain **placeholder** account ids (111111111111 and so on) until you do this.

## Install by hand (Argo CD does the same in Phase 19)

```bash
aws eks update-kubeconfig --name school-dev --region ap-south-1
scripts/helm/install-addons.sh dev                                  # load balancer controller + metrics-server (once per cluster)

kubectl create namespace school-dev
kubectl label namespace school-dev pod-security.kubernetes.io/enforce=restricted pod-security.kubernetes.io/warn=restricted

helm upgrade --install school-platform helm/school-platform -n school-dev \\
  -f helm/environments/dev/common.yaml -f helm/environments/dev/platform.yaml --wait --timeout 15m
# ^ runs the database bootstrap job; read its log:  kubectl -n school-dev logs job/db-bootstrap

for svc in auth student admission fee attendance notification; do
  helm upgrade --install $svc helm/school-service -n school-dev \\
    -f helm/services/$svc.yaml -f helm/environments/dev/common.yaml -f helm/environments/dev/$svc.yaml --wait --timeout 10m
done
```
Before this works, `image.tag` in each `helm/environments/dev/<service>.yaml` (and `platform.yaml`) must name a commit SHA that CI
has built and pushed to ECR. The committed `0000000` is a placeholder no build produces.

## Verify

```bash
kubectl -n school-dev get pods                          # all Running; the notification worker too
kubectl -n school-dev get ingress                       # one ADDRESS (the shared load balancer) for every service
kubectl -n school-dev get hpa                           # prod only: TARGETS shows a percentage, not <unknown>
kubectl -n school-dev logs deploy/fee --tail=20         # JSON lines; "service started"
kubectl -n school-dev exec deploy/fee -- id             # uid=10001
kubectl -n school-dev get cronjob                       # fee-overdue-reminders
aws elbv2 describe-rules --listener-arn <listener>      # the rules in the order described in ADR 0008, D73
```

## Troubleshooting

| Symptom | Likely cause | Check | Fix |
|---|---|---|---|
| Pod `ImagePullBackOff` | Tag not in ECR; or no pull permission; or wrong architecture | `kubectl describe pod`: the event names the cause | Push the image (CI); check the node role and the registry's cross-account policy; images must be linux/amd64 |
| Pod `CrashLoopBackOff` and the log says `could not read secret ...: AccessDeniedException` | The pod has no AWS role: service account name or namespace differs from Terraform's Pod Identity association | `aws eks list-pod-identity-associations --cluster-name school-dev` | Names must match exactly (service = service account, namespace `school-<env>`) |
| Log says `could not read secret ...: EndpointConnectionError` or credentials error | Network policy blocks the Pod Identity agent, or no route to AWS | `kubectl describe networkpolicy <service>`; is `169.254.170.23` allowed? | Fix the policy; add VPC endpoints or check NAT |
| Release fails at `pre-upgrade` (the migration job) | The migration failed; the deploy correctly stopped | `kubectl -n school-dev logs job/<service>-migrate` | Fix the migration; the old version is still running |
| Migration job: `permission denied` / role does not exist | The bootstrap job has not run, or failed | `kubectl -n school-dev logs job/db-bootstrap` | Re-run `helm upgrade school-platform ...` |
| Pods `Running` but not `Ready` | `/ready` fails: the database is unreachable | `kubectl logs`: "readiness check failed" | Security group rule from the cluster to the database; the secret's host name |
| Ingress has no ADDRESS | The load balancer controller is not running, or the subnets lack the `kubernetes.io/role/elb` tag | `kubectl -n kube-system logs deploy/aws-load-balancer-controller` | Install the add-ons; check subnet tags |
| ALB returns 503/504 | Target not healthy: network policy blocks the load balancer, or the security group rule is missing | Target group health in the console; `kubectl describe networkpolicy` | The policy allows the VPC CIDR on the container port |
| `/students/{id}/fees` returns the Student service's answer | Route order wrong | Ingress annotations `group.order` | Fee and Attendance must have a LOWER order number than Student |
| HPA `<unknown>` | metrics-server missing | `kubectl top pods` | `scripts/helm/install-addons.sh` |
| `Error: values don't meet the specifications of the schema` | Typo or bad value | The message names the key | Fix the values file |
| `forbidden: violates PodSecurity "restricted"` | A pod spec broke the profile | The message names the field | Fix the chart; do not weaken the namespace label |
