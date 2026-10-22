# Roadmap

Status refers to this portfolio prototype, not an enterprise product.

## Completed / demonstrated locally

- [x] Local PostgreSQL lab and synthetic `demo_accounts` table.
- [x] FastAPI-based local API and browser dashboard.
- [x] Live diagnostic data for supported activity/blocking checks.
- [x] Manually reproducible row-lock incident and independent SQL verification.
- [x] Initial lock-related investigation guidance.

## Next milestones

- [x] Save manually triggered timestamped diagnostic snapshots with explicit collection time.
- [x] Build a local incident history list and snapshot detail view.
- [x] Add configurable automatic periodic collection for sessions, blocking, long queries and idle transactions.
- [x] Persist automatic samples locally with seven-day sample retention.
- [x] Add threshold-based event timeline and a more graphical dashboard.
- [ ] Add PostgreSQL server-log ingestion for failed SQL, errors, slow statements and lock-wait/deadlock messages.
- [ ] Compare snapshots to highlight changes and support event-centered evidence bundles.
- [ ] Export a sanitized incident report as JSON/Markdown.
- [ ] Add tests for API endpoints and diagnostic query results.
- [ ] Add structured error handling and clear UI loading/empty/error states.
- [ ] Add query-plan guidance for user-selected, sanitized SQL in a local lab.
- [ ] Add connection pressure detection validated against server-wide statistics.
- [ ] Add a two-node replication lab before claiming replication-lag detection.
- [ ] Add automated checks/linting and CI.
- [ ] Complete security review before any non-local deployment.

## Out of scope until properly designed

- Automatically terminating sessions or changing customer databases.
- Connecting to production systems without explicit authorization and security review.
- Claiming guaranteed root cause from heuristics alone.


## Milestone: timestamped evidence and incident history (v0.3)

Status: implemented as manual point-in-time capture in the local prototype.

- `POST /api/history/capture` runs diagnostic checks and stores a UTC timestamp, title/notes, findings, lock relationships, activity rows and connection counts.
- `GET /api/history` lists up to 100 snapshots, newest first.
- `GET /api/history/{snapshot_id}` returns one snapshot and its evidence payload.
- Snapshot metadata and JSON payload are stored in `data/incident_history.sqlite3`. The database is local and ignored by Git.
- The dashboard includes Capture evidence, Incident history, View snapshot, and saved evidence JSON.

Limitations: collection is manual, not periodic; no incident grouping, automatic comparison, retention policy, access control or redaction pipeline exists yet. Evidence may include SQL text and client metadata. Do not use production data or share history files without review.

## Next milestone

1. Add a configurable periodic collector with safe interval limits and a visible on/off control.
2. Compare snapshots to highlight changes in blocker PIDs, session counts and findings.
3. Group snapshots under an incident ID and add operator notes.
4. Add retention/export controls and SQL-text redaction before sharing.
5. Add tests for API routes, persistence across restart, empty history and database connection errors.

## Milestone: automatic sampling and dashboard (v0.4)

Status: implemented as a local prototype; syntax-checked, but validate against the user's PostgreSQL version and permissions before relying on it.

- Background polling defaults to every 15 seconds; minimum configured interval is 10 seconds.
- Samples include active sessions, blocking relationships, long-running active queries, idle-in-transaction sessions, connection distribution and selected `pg_stat_database` counters.
- Sample history is retained for seven days. Event transitions are recorded when sampled signals appear and clear.
- Manual snapshots include an additional diagnostic payload.
- UI has summary metric cards, a session trend chart, signal list, session/long-query/idle-transaction tables, blocking view, timeline, evidence history and database stats.

Limitations: polling can miss short events; PostgreSQL errors and failed statements are not ingested in this version. Configure server logging before implementing log ingestion; see `postgres-logging.md`. This is not a complete audit trail or production monitoring product.
