-- Run as a PostgreSQL administrator on the dedicated monitoring/test cluster.
-- Replace the password before executing. The role is not a superuser and receives
-- PostgreSQL's built-in monitoring role, not write access to application tables.
CREATE ROLE incident_monitor LOGIN PASSWORD 'REPLACE_WITH_A_STRONG_PASSWORD';
GRANT pg_monitor TO incident_monitor;
GRANT CONNECT ON DATABASE incident_intelligence_lab TO incident_monitor;
