-- Creates ONE service's schema and its two roles. Safe to re-run (it also rotates the passwords).
--
--   :schema    schema name, e.g. admission
--   :migrator  role that owns the schema and runs migrations (can CREATE/ALTER/DROP tables)
--   :app       role the running service uses (can only read and write rows)
--   :migrator_pw, :app_pw   passwords. They arrive as psql variables, so they never appear in a file in Git.
--
-- Why two roles? A bug or injection in the running service then cannot alter or drop tables.
\set ON_ERROR_STOP on

SELECT format('CREATE ROLE %I LOGIN', :'migrator')
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'migrator') \gexec
SELECT format('CREATE ROLE %I LOGIN', :'app')
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app') \gexec
SELECT format('ALTER ROLE %I WITH LOGIN PASSWORD %L', :'migrator', :'migrator_pw') \gexec
SELECT format('ALTER ROLE %I WITH LOGIN PASSWORD %L', :'app', :'app_pw') \gexec

SELECT format('CREATE SCHEMA IF NOT EXISTS %I AUTHORIZATION %I', :'schema', :'migrator') \gexec

-- The service's code never writes "admission.applications": it just says "applications", and the role's
-- search_path resolves that to its own schema. Another service's tables are not even visible.
SELECT format('ALTER ROLE %I SET search_path = %I', :'migrator', :'schema') \gexec
SELECT format('ALTER ROLE %I SET search_path = %I', :'app', :'schema') \gexec

SELECT format('GRANT CONNECT ON DATABASE %I TO %I, %I', current_database(), :'migrator', :'app') \gexec
SELECT format('GRANT USAGE ON SCHEMA %I TO %I', :'schema', :'app') \gexec

-- Tables the migrator creates later are automatically usable by the app role. No DELETE or TRUNCATE:
-- these services never delete rows (cascades run with the table owner's rights, not the app role's).
SELECT format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I GRANT SELECT, INSERT, UPDATE ON TABLES TO %I',
              :'migrator', :'schema', :'app') \gexec
SELECT format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I GRANT USAGE, SELECT ON SEQUENCES TO %I',
              :'migrator', :'schema', :'app') \gexec
