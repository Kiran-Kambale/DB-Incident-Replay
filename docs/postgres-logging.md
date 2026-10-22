# PostgreSQL server logging: failed queries and incident evidence

DB Incident Replay v0.4 does not currently read PostgreSQL server log files. The automatic collector polls live views; a failed query can disappear from `pg_stat_activity` immediately, so polling alone cannot preserve the failed statement.

## Recommended local-lab starting point

Review your PostgreSQL version and existing configuration first. The following are settings to discuss/test in a disposable local lab; some settings require a server restart and others require a reload. Do not apply them blindly to a production server.

```conf
# Ensure server messages are written to log files (exact setup depends on platform)
logging_collector = on
log_destination = 'stderr'
log_directory = 'log'
log_filename = 'postgresql-%Y-%m-%d_%H%M%S.log'

# Preserve SQL text associated with errors; this is not a substitute for access controls
log_min_error_statement = error

# Capture slow statements over one second (adjust to workload and log volume)
log_min_duration_statement = 1000

# Make lock waits and deadlock evidence easier to correlate
log_lock_waits = on
deadlock_timeout = '1s'

# Include time, PID, database, user and application where supported
log_line_prefix = '%m [%p] db=%d,user=%u,app=%a,client=%h '
```

### Safety notes

- `logging_collector` normally requires a server restart when changed; use `pg_settings` (`context`, `pending_restart`) to verify how a setting applies on your version. Use a reload only for settings that support it.
- Slow-query logging can create substantial volume. Set a threshold that matches the lab workload and ensure log rotation/retention.
- Error and statement logs can include literal values, personal data, tokens, or other secrets. Restrict filesystem permissions and redact before sharing.
- Avoid `log_statement = 'all'` as a default: it can produce excessive volume and sensitive content.
- Managed cloud PostgreSQL services may expose logs through provider-specific export settings instead of local log files.
- A future log ingestor should be read-only, support log rotation and multi-line statements, normalize timestamps/time zones, handle duplicate records, redact sensitive values, and document dropped/unparseable lines. It should not assume every logged error is caused by the database engine; applications can submit invalid SQL or cancel statements.

## Validate in the lab

1. Check current settings using `SHOW logging_collector;`, `SHOW log_min_error_statement;`, `SHOW log_min_duration_statement;`, `SHOW log_lock_waits;`, and `SHOW log_line_prefix;`.
2. Configure and reload/restart as required for the specific setting and PostgreSQL installation.
3. Run a deliberate harmless error in the local lab, such as `SELECT 1 / 0;`, and verify the corresponding log record exists.
4. Run a query that exceeds the configured duration and verify the slow-query entry.
5. Confirm log file access is restricted before considering any integration with DB Incident Replay.
