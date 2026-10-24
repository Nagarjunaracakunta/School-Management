-- Run ONCE per database, as an administrator. Safe to re-run.
-- Locks the database down so that only roles we grant access to can connect and create things.
\set ON_ERROR_STOP on

-- Nobody gets anything just for existing. Each service role is granted exactly what it needs below.
SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database()) \gexec
REVOKE ALL ON SCHEMA public FROM PUBLIC;
