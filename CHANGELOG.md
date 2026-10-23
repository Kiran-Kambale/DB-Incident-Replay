# Changelog

## v0.5.0 — Failed SQL log ingestion
- Added `GET /api/diagnostics/failed-queries` to discover the active PostgreSQL log and parse recent ERROR/FATAL/PANIC records with DETAIL, HINT, and STATEMENT lines when present.
- Added a live failed-SQL panel to the dashboard with ingestion status and warnings.
- Supports `PG_LOG_FILE` as an optional explicit log path and `PG_LOG_TAIL_BYTES` to bound the scan (default 2 MiB, maximum 10 MiB).
- Limitations: scans only the current log file tail; no rotation archive ingestion, durable log index, or full audit guarantee. SQL text can contain secrets.


## v0.4.0 — automatic sampling and flight-recorder dashboard

- Added configurable background sampling of current sessions, blocking relationships, long-running active queries, idle-in-transaction sessions, connection distribution and selected database counters.
- Added seven-day retention for automatic samples in local SQLite storage.
- Added threshold-based incident events that open/clear based on sampled signals.
- Redesigned the dashboard with metric cards, session trend chart, incident signals, query/session tables, blocking view, timeline, evidence history and database counters.
- Manual snapshots now include an additional monitor-evidence payload when available.
- Added server logging guide for failed statements, slow queries, lock waits and deadlocks.

### Known limitations

- Polling can miss events shorter than the sampling interval; this is not a complete audit trail.
- Failed-SQL ingestion was added in v0.5; it scans only the current log tail and is not a complete audit trail.
- This is a local portfolio prototype, not production-ready monitoring software.
