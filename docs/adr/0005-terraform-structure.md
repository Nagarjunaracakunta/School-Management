# ADR 0005: Terraform structure

Status: Accepted
Date: 2026-10-24

Builds on D7 (monorepo) and D9 (S3 backend with a native lock file).

| # | Decision | Reason | Revisit when |
|---|---|---|---|
| D38 | One directory per environment (`environments/dev`, `stage`, `prod`), not Terraform workspaces | Each environment has its own state, its own committed values, its own backend. A workspace is a hidden switch you can forget you flipped, with the same code and the same backend for every environment. A directory is visible in the path, in the PR and in the pipeline | Never expected |
| D39 | Separate AWS accounts for dev, stage and prod, each with its own state bucket (created by `terraform/bootstrap`) | A mistake or a leaked credential in dev cannot reach prod. State and permissions are separated by the account boundary, not by convention | A single account is all that is available (then use separate state keys and strict IAM) |
| D40 | The three environment directories contain **identical** `.tf` files; only `backend.tf`, `backend.hcl` and `terraform.tfvars` differ. `scripts/tf/check.sh` fails if they drift | The differences between environments are DATA, visible in one small file, not logic hidden in three diverging copies | Environments need genuinely different resources (then give that resource its own module and a flag) |
| D41 | Modules are local folders referenced by relative path (`../../modules/vpc`) | One repository, changed and reviewed together. No version juggling while learning | A module is shared by other repositories: publish it and pin it to a Git tag |
| D42 | Providers are pinned (`~> 6.0`) and `.terraform.lock.hcl` is committed with checksums for macOS (arm64) and Linux (amd64) | The laptop and the CI runner use exactly the same provider build; a surprise upgrade cannot change a plan | A provider upgrade is deliberate: `terraform init -upgrade`, review, commit the lock |
| D43 | `allowed_account_ids` on every provider, and `terraform_data.guardrails` preconditions in every environment | The wrong credentials or a bad tfvars value fail at plan time, before anything is built | Never expected |
| D44 | Tests run offline with `terraform test` and a mocked AWS provider; CI runs the same `scripts/tf/check.sh` | Fast, free, no credentials, and they catch real mistakes (see the mutation check in the Phase 12 write-up). They test our logic, not AWS | We add integration tests that apply to a throwaway account (Terratest or `terraform test` with a real provider) |
| D45 | Dev owns the ECR registry; stage and prod pull from it (cross-account pull policy) | "Build once, promote the same image": the image that passed in dev is byte-for-byte the one that runs in prod | A tooling account owns all registries |
| D46 | NAT gateways are a switch (`none` / `single` / `per_az`), with prod forced to `per_az` | NAT gateways are the largest fixed cost of a small AWS network. Dev saves money, prod keeps each zone independent | Traffic grows enough to justify endpoints for every service |
