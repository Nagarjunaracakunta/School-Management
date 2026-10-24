# ADR 0007: The Kubernetes cluster (EKS)

Status: Accepted
Date: 2026-10-24

| # | Decision | Reason | Revisit when |
|---|---|---|---|
| D56 | **Managed node group** (EC2 machines AWS patches and rolls) plus the **AWS Load Balancer Controller**. Not EKS Auto Mode, not Fargate | Managed nodes show how a cluster really works (nodes, IAM, networking, the controller) and cost less per unit. Auto Mode hides those parts. Fargate has no DaemonSets (our Pod Identity agent is one) and charges per pod | The team is small and wants less to operate: try Auto Mode |
| D57 | Terraform builds the cluster, its IAM and the AWS-side add-ons. **Everything inside the cluster** (the load balancer controller, metrics-server, our own services) is installed with Helm and Argo CD (Phases 15 and 19) | A Kubernetes/Helm provider in the same Terraform run as the cluster needs credentials for a cluster that does not exist yet, and a failed apply leaves a half-configured cluster | Never expected |
| D58 | Who may use kubectl is decided by **EKS access entries** (`authentication_mode = API`); nobody is admin by default, not even the creator | The old `aws-auth` ConfigMap can be broken by anyone with edit rights and locks everyone out when it is. Access entries are AWS API objects with audit trail | Never expected |
| D59 | The Kubernetes API is reachable from the internet only from **listed addresses** (never 0.0.0.0/0, which the module refuses), and always privately from inside the VPC | The API is the most valuable door in the platform | A VPN or bastion exists: switch the public endpoint off |
| D60 | Kubernetes Secrets are encrypted in the cluster database with a dedicated, rotating KMS key | Secrets are only base64 by default. If etcd's storage is exposed, they stay unreadable | Never expected |
| D61 | Nodes require **IMDSv2 with hop limit 1** and encrypted disks; there are no SSH keys and no port 22 (shell access is through SSM) | A pod, or a request-forgery bug in an app, cannot reach the node's own AWS credentials. Pods get their permissions from Pod Identity instead | Never expected |
| D62 | Nodes are **x86_64**; CI builds `linux/amd64` images | Images built on an Apple Silicon laptop are arm64 and fail on these nodes with `exec format error`. Only CI builds what is deployed | We move to Graviton (arm64) nodes for cost: build multi-architecture images |
| D63 | All five control-plane log types go to CloudWatch with a retention period | The audit log answers "who changed that?" | Log cost matters: keep audit and authenticator, drop the rest |
| D64 | One cluster per environment (each in its own AWS account), one namespace named `school-<env>` | Environment isolation by account, not by namespace | Cost pressure: dev and stage could share a cluster (weaker isolation) |

## Cost reality

The EKS control plane costs roughly USD 73 per month **per cluster** whether or not anything runs, and there is one per
environment. With the NAT gateways, the nodes and the database, a dev environment left running costs on the order of a few
hundred USD a month. Destroy dev when you are not using it (`terraform destroy`), and rebuild it from code when you are.
