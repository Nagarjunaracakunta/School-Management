# ADR 0002: Database migrations and roles

Status: Accepted
Date: 2026-10-24

Builds on D5 in [ADR 0001](0001-core-architecture-decisions.md): one RDS PostgreSQL instance, one schema per service.

| # | Decision | Reason | Revisit when |
|---|---|---|---|
| D12 | Schema changes are Alembic migrations stored in each service (`services/<svc>/migrations`). Services never create tables on startup in dev/stage/prod (`AUTO_CREATE_TABLES` is for laptops and tests only) | Every change is reviewed, versioned, repeatable and reversible. Starting pods must not race to alter the schema | Never expected |
| D13 | Two database roles per service: `<svc>_migrator` (owns the schema, can change it) and `<svc>_svc` (reads and writes rows only: SELECT, INSERT, UPDATE; no DELETE, no DDL) | A bug or SQL injection in the running service cannot drop or rewrite tables. Cascading deletes run with the table owner's rights, so the app role does not need DELETE | A service genuinely needs to delete rows (then grant DELETE on that one table) |
| D14 | Code never names a schema. Each role's `search_path` points at its own schema | The same code and migrations run unchanged in every environment, and a service cannot see another service's tables | We move to one database instance per service (nothing in the code changes) |
| D15 | Migrations run as a Kubernetes Job BEFORE the new app version starts (Argo CD pre-sync hook), using the migrator role. Rolling updates mean old and new code run together briefly, so migrations must be backward compatible ("expand, then contract") | Keeps DDL credentials out of the app pods and avoids two pods migrating at once | Never expected |
| D16 | Passwords are never in files in Git. Locally, `scripts/db/bootstrap.sh` generates them into `.dev-secrets/` (git-ignored). In AWS they live in Secrets Manager | Rule from the project brief: no credentials in source | Never expected |
| D17 | The database enforces the domain rules as CHECK constraints (valid statuses, positive amounts, `amount_paid <= amount_due`), in addition to application validation | Defence in depth: a future bug in application code still cannot store impossible data | Never expected |
| D18 | Every constraint and index has an explicit, predictable name (SQLAlchemy naming convention) | Without it the database invents names, which makes migrations that drop or compare them unreliable | Never expected |

## Expand, then contract

Rolling deployments run version N and N+1 side by side. Therefore:

1. **Adding a column:** one migration, new column nullable (or with a default). Then ship code that uses it.
2. **Removing or renaming a column:** first ship code that no longer uses it. Only then ship the migration that drops it, in a later release.
3. **Never** drop or rename in the same release as the code change.
