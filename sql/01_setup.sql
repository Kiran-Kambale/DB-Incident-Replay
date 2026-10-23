-- Run as a local PostgreSQL administrator in psql or pgAdmin.
CREATE DATABASE incident_lab;
-- Connect to incident_lab before running the remainder of this file.
-- In psql: \c incident_lab
CREATE ROLE incident_reader LOGIN PASSWORD 'change_this_local_password';
GRANT CONNECT ON DATABASE incident_lab TO incident_reader;
GRANT pg_read_all_stats TO incident_reader;
-- v0.5 local failed-SQL log discovery permissions. Review before using outside a lab.
GRANT pg_monitor TO incident_reader;
GRANT EXECUTE ON FUNCTION pg_catalog.pg_current_logfile() TO incident_reader;

CREATE TABLE IF NOT EXISTS public.demo_accounts (
  account_id integer PRIMARY KEY,
  owner_name text NOT NULL,
  balance numeric(12,2) NOT NULL DEFAULT 1000
);
INSERT INTO public.demo_accounts(account_id, owner_name, balance)
VALUES (1, 'Demo Alice', 1000), (2, 'Demo Bob', 1000)
ON CONFLICT (account_id) DO NOTHING;
GRANT USAGE ON SCHEMA public TO incident_reader;
GRANT SELECT ON public.demo_accounts TO incident_reader;
