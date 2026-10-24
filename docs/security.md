# Security model

## Three different questions

| Question | Mechanism | Who answers | Example in this project |
|---|---|---|---|
| **Authentication**: who are you? | Email + password, then a signed token | Auth Service | `POST /api/v1/auth/login` returns a JWT that proves "this is Ravi" |
| **Authorization**: what may you do? | Role in the token (RBAC) plus data-ownership rules | **Each** service, on every request | A parent may read only their own children's fees; a teacher marks only their own sections |
| **AWS IAM**: what may this *AWS identity* do? | IAM roles and policies | AWS | The Fee pod's role may `sqs:SendMessage` to one queue and read one secret, nothing else |

They are independent. A valid token says nothing about AWS permissions, and an IAM role says nothing about which student a
parent may see. A request must pass all that apply.

## How a request is checked

```
Browser --(JWT)--> CloudFront --> ALB --> service pod
                                           1. verify signature, issuer, audience, expiry   (is the token genuine?)
                                           2. require_roles(...)                           (may this role call this endpoint?)
                                           3. ownership rules in the query                 (may they see THIS record?)
                                           4. database role (<svc>_svc)                    (what can the service itself do?)
                                           5. IAM role via EKS Pod Identity               (what can the pod do in AWS?)
```

## Who can do what (verified live, all six services)

| Request | anonymous | parent | teacher | admin |
|---|---|---|---|---|
| `GET /users` | 401 | 403 | 403 | 200 |
| `GET /auth/me` | 401 | 200 | 200 | 200 |
| `GET /admissions` | 401 | 200 (own) | 403 | 200 |
| `GET /students` | 401 | 200 (own children) | 200 (own sections) | 200 |
| `POST /classes` | 401 | 403 | 403 | 201 |
| `GET /fees` | 401 | 200 (own children) | 403 | 200 |
| `GET /attendance` | 401 | 200 (own children) | 200 (own sections) | 200 |
| `POST /attendance` | 401 | 403 | 200/422 | 200/422 |
| `GET /notifications` | 401 | 200 (own) | 200 (own) | 200 |
| `POST /notifications` | 401 | 403 | 403 | 201/422 |

## AWS permissions per service (EKS Pod Identity roles, enforced by `modules/iam`)

| Role | Secrets Manager | SQS (events queue) | SNS |
|---|---|---|---|
| auth | its DB login, public key, **private signing key** | none | none |
| student | its DB login, public key | none | none |
| admission, fee, attendance | its DB login, public key | **send only** | none |
| notification (API and worker) | its DB login, public key | **receive, delete, extend visibility** | **publish to the notifications topic** |
| db-migrator (job) | the DB administrator login, every migrator and app login | none | none |

The module refuses any wildcard action or resource, and the environment tests assert each row above. The delivery
Lambda can send email only from the one verified address and may text phone numbers, but is explicitly **denied** from
publishing to any SNS topic.

## Kubernetes hardening already in place (Phase 14)

| Control | What it prevents |
|---|---|
| API reachable from the internet only from listed addresses; never 0.0.0.0/0 | Anyone on the internet probing or attacking the Kubernetes API |
| EKS access entries; nobody is admin by default | A forgotten or leaked cluster-admin; lock-out from a broken ConfigMap |
| Kubernetes Secrets encrypted with a rotating KMS key | Reading secrets from a stolen cluster database |
| Nodes: IMDSv2 only, hop limit 1, encrypted disks, no SSH | A pod or an SSRF bug borrowing the node's AWS credentials; disk theft |
| Pod Identity roles, one per service | One compromised service reaching another's secrets or queues |
| Control-plane audit log kept in CloudWatch | "Who did that?" having no answer |
| Database firewall opened to the cluster's security group only | Any other machine in the VPC reaching PostgreSQL |

## Workload hardening (Phase 15, enforced by the chart and its tests)

| Control | What it prevents |
|---|---|
| Namespace enforces the Kubernetes *restricted* pod profile | A mis-written manifest running a privileged or root container |
| Non-root (10001), read-only filesystem, no capabilities, seccomp `RuntimeDefault` | A compromised process modifying itself, installing tools or escalating |
| No Kubernetes API token mounted | A compromised pod using the cluster API |
| Default-deny NetworkPolicy; each service opens only its own paths | A compromised pod reaching other services or scanning the network |
| Secrets read from Secrets Manager at startup with the pod's own role; no Kubernetes `Secret` objects | Secrets in etcd, in backups, or visible to anyone with `kubectl get secret` |
| Memory limits on every container | One leaking service starving the others on a node |
| Image tags must be a commit SHA; the schema refuses `latest` | Deploying something nobody can trace to a commit |
| Migration job uses the only service account allowed to read schema-changing logins | The running service ever holding rights to alter or drop tables |


## Threats and what answers them

| Threat | Defence |
|---|---|
| Guessing passwords | Argon2id, 5-attempt lockout, generic errors. Per-IP rate limiting at the edge (AWS WAF) is NOT deployed yet: the CloudFront module accepts a web ACL, nothing creates one (ADR 0006) |
| Finding which emails are registered | Same message and similar timing for every failure |
| Stolen database | Only Argon2id hashes are stored |
| Forged token | RS256: only the Auth Service holds the private key; algorithm is pinned (`alg: none` rejected) |
| Stolen token | 30-minute lifetime, HTTPS only; a disabled account cannot log in again |
| Reading another family's data | Ownership is part of the SQL query; a foreign record looks like "not found" (404, not 403) |
| A compromised service | Its database role cannot delete rows, change tables or see other schemas; its IAM role is scoped to its own queue/secret |
| Secrets in Git | None are stored: passwords, keys and database credentials come from the environment / Secrets Manager |
| Log leaks | Passwords never logged; emails and phone numbers are masked in logs |

## Known limits (deliberate, see ADR 0003)

- A disabled user's token keeps working until it expires (up to 30 minutes).
- There are no refresh tokens, no multi-factor authentication, and no self-service "forgot password" (an admin resets it).
- Password strength is checked against a small list, not a breach database.
