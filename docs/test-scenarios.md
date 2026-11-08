# Local PostgreSQL test scenarios

Run these only against a dedicated disposable database such as `incident_intelligence_lab`, never against production.

## Prepare the test database

```bash
createdb incident_intelligence_lab
psql -d incident_intelligence_lab -f sql/create_test_lab.sql
```

Configure `.env` to point the collector at the same database. A monitoring role with `pg_monitor` is recommended; see `sql/grant_monitor_role.sql` and the README.

## Test 1 — Long-running active query

Open a second terminal and connect to `incident_intelligence_lab`:

```sql
SELECT pg_sleep(45);
```

Keep the query running. With `LONG_QUERY_SECONDS=30` and a 10-second collection interval, the dashboard should record a `long_query` finding on a sample taken after the threshold. It should resolve after the query finishes and a later successful sample observes no qualifying query.

## Test 2 — Idle in transaction

In a separate psql session:

```sql
BEGIN;
SELECT * FROM ii_test.accounts WHERE account_id = 1;
-- Leave this session open for at least 70 seconds.
```

The collector should record an `idle_in_transaction` finding when `IDLE_TRANSACTION_SECONDS=60`. Then run `ROLLBACK;` to release the transaction.

## Test 3 — Blocking session / lock wait

Use two psql sessions connected to `incident_intelligence_lab`.

Session A:

```sql
BEGIN;
UPDATE ii_test.accounts SET balance = balance + 10, updated_at = clock_timestamp() WHERE account_id = 1;
-- Do not commit yet.
```

Session B:

```sql
UPDATE ii_test.accounts SET balance = balance + 20, updated_at = clock_timestamp() WHERE account_id = 1;
-- This statement waits for Session A's row lock.
```

The dashboard should capture a lock-wait sample, including the blocked PID and `pg_blocking_pids()` result when the monitoring role has sufficient visibility.

Cleanup: run `ROLLBACK;` in Session A and Session B. If Session B has been cancelled or failed, reconnect before continuing.

## Test 4 — Connection-slot utilization (optional)

Use a dedicated test cluster with a deliberately low `max_connections`, or open a controlled set of additional sessions. Do not exhaust connections on a shared or production server. The product reports a sampled ratio of visible client backends to `max_connections`; it does not claim that connection attempts were rejected.

## Test 5 — Deadlock counter (advanced, optional)

Use two sessions and two rows. Session A locks row 1; Session B locks row 2. Then have Session A update row 2 and wait; have Session B update row 1. PostgreSQL should abort one transaction to break the deadlock. The collector can detect an increase in the database deadlock counter between samples, but it cannot identify the exact SQL involved from that counter alone. Use PostgreSQL logs for that.

## Expected verification

- Each finding should show its first and last observed timestamps.
- A finding should resolve after a successful sample no longer observes its condition.
- The downloaded Markdown report should state the threshold, captured facts, evidence coverage and investigation hypotheses.
- Open the incident detail and verify the timeline includes baseline, observed and (after cleanup) condition-not-detected / resolved events where snapshots exist.
- Check the before/during/after table. A dash means there was no sample for that metric/period, not a measured zero.
- Read the hypothesis card. Verify supporting evidence, missing evidence and next checks against `pg_stat_activity`, `pg_blocking_pids()` and PostgreSQL logs.
- Confirm business impact remains `NOT MEASURED`; do not infer affected users or revenue from database session counts alone.
- The report must not label a hypothesis as a confirmed root cause.
