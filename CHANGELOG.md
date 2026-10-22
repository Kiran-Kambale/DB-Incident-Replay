# Changelog

## v0.4.0 — automatic sampling and flight-recorder dashboard

- Added configurable background sampling of current sessions, blocking relationships, long-running active queries, idle-in-transaction sessions, connection distribution and selected database counters.
- Added seven-day retention for automatic samples in local SQLite storage.
- Added threshold-based incident events that open/clear based on sampled signals.
- Redesigned the dashboard with metric cards, session trend chart, incident signals, query/session tables, blocking view, timeline, evidence history and database counters.
- Manual snapshots now include an additional monitor-evidence payload when available.
- Added server logging guide for failed statements, slow queries, lock waits and deadlocks.

### Known limitations

- Polling can miss events shorter than the sampling interval; this is not a complete audit trail.
- PostgreSQL server logs are not ingested in this version. Failed statements require server-side logging and a future deployment-specific log ingestor.
- This is a local portfolio prototype, not production-ready monitoring software.
