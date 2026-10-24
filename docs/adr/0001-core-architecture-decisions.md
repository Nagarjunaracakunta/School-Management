# ADR 0001: Core architecture decisions

Status: Accepted
Date: 2026-10-24

An ADR (Architecture Decision Record) is a short note explaining *why* we chose something,
so future readers don't have to guess.

| # | Decision | Reason | Revisit when |
|---|---|---|---|
| D1 | CloudFront is the single entry point: `/*` to S3, `/api/*` to ALB | One domain, no CORS, one TLS/WAF point | Never expected |
| D2 | No API Gateway in the main path | ALB already does path routing; avoids a duplicate layer | We expose a public API to third parties or need per-client throttling |
| D3 | Notification Service consumes SQS itself (worker Deployment, same image) | Service owns its data and retry logic | Throughput needs independent scaling beyond HPA |
| D4 | ~~Lambda only for scheduled overdue-fee reminder and DLQ alert~~ **Superseded by [ADR 0006](0006-aws-resources.md):** a CloudWatch alarm replaces the DLQ alert, a Kubernetes CronJob replaces the reminder, and one Lambda delivers notifications (SNS to SES/SMS) | Small event-driven glue suits Lambda; CRUD APIs do not | n/a |
| D5 | One RDS PostgreSQL instance, one schema and one DB user per service, no cross-schema foreign keys | Cheap to learn on; keeps boundaries so schemas can be split out later | Prod: move to an instance per service |
| D6 | Separate Auth Service issues JWTs (RS256) | Learn JWT and RBAC in Python | Enterprise: replace with Amazon Cognito or the corporate IdP |
| D7 | Monorepo for code, Terraform and Helm; separate GitOps repo for environment state | CI can bump image tags without retriggering itself; prod approvals are separate | n/a |
| D8 | GitHub Actions to AWS via OIDC; no long-lived access keys | Short-lived credentials, nothing to leak | n/a |
| D9 | Terraform S3 backend with native lockfile (`use_lockfile = true`, Terraform 1.10+) | No DynamoDB table to manage | Org standard still requires DynamoDB |
| D10 | One shared Helm chart (`helm/school-service`) used by all services, with per-service values | Six near-identical charts would drift apart | A service needs a fundamentally different shape |
| D11 | Tests live in `services/<svc>/tests/`, next to `app/`, not inside it | Tests are not shipped in the Docker image | n/a |
