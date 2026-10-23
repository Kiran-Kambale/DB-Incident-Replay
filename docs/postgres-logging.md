# PostgreSQL server logging: failed queries and incident evidence

DB Incident Replay v0.5 can read the recent tail of the active PostgreSQL server log for failed-SQL evidence. The automatic collector polls live views; a failed query can disappear from `pg_stat_activity` immediately, so polling alone cannot preserve the failed statement.

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


## v0.5 local log ingestion and permissions

The application exposes `GET /api/diagnostics/failed-queries`. It asks PostgreSQL for `pg_current_logfile()` and `data_directory`, reads only the recent tail of the current log, and parses `ERROR`, `FATAL`, and `PANIC` records plus nearby `DETAIL`, `HINT`, and `STATEMENT` entries. The API database login may require `pg_monitor` membership and EXECUTE permission on `pg_catalog.pg_current_logfile()`; the local example setup SQL includes these grants. Review their scope before granting them outside a disposable lab. If auto-discovery is unavailable, set `PG_LOG_FILE` in the local `.env` to an absolute path readable by the app process. `PG_LOG_TAIL_BYTES` controls the scan size (default 2 MiB, maximum 10 MiB).

This is a local prototype, not a complete audit trail: it does not ingest rotated logs, persist parsed errors separately, or guarantee association for every multiline statement. Do not expose this endpoint publicly; SQL text can contain sensitive literals.
