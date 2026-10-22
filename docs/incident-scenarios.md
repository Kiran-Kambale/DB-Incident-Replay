# Incident Lab Scenarios

Run these only against your local `incident_lab` database. Keep the dashboard API bound to `127.0.0.1`. These tests use synthetic data.

## Scenario 1 — Row-lock blocking (supported demo)

### Goal

Create a blocker and a blocked session, detect the relationship, verify the PIDs independently, and resolve the test safely.

### Session A: create the blocker

```sql
BEGIN;
UPDATE demo_accounts
SET balance = balance + 10
WHERE account_id = 1;
```

Expect `UPDATE 1`. Leave the transaction open.

### Session B: create the blocked query

```sql
UPDATE demo_accounts
SET balance = balance + 20
WHERE account_id = 1;
```

It should wait. Do not cancel it yet.

### Dashboard

Click **Run diagnostics** while Session B is waiting. Record the blocker PID, blocked PID, wait type and query evidence displayed by the dashboard.

### Independent verification

Run this from a third SQL session connected to `incident_lab`:

```sql
SELECT
    a.pid AS blocked_pid,
    a.usename AS blocked_user,
    a.application_name,
    a.state,
    a.wait_event_type,
    a.wait_event,
    pg_blocking_pids(a.pid) AS blocker_pids,
    now() - a.query_start AS query_duration,
    a.query AS blocked_query
FROM pg_stat_activity AS a
WHERE cardinality(pg_blocking_pids(a.pid)) > 0;
```

The blocked PID should match Session B and `blocker_pids` should contain Session A's PID. Visibility depends on database role permissions.

### Resolve and confirm

Run `COMMIT;` in Session A. Session B should finish. Refresh the dashboard; the blocking relationship should disappear. This validates detection of the current state, not historical replay.

If the test is complete and both sessions have finished, an administrator may reset the sample balance:

```sql
UPDATE demo_accounts SET balance = 1000;
```

## Scenario 2 — Active query visibility

Run this in a separate session:

```sql
SELECT pg_sleep(25);
```

While it runs, refresh the dashboard. If permissions and the implementation allow it, the active query and its duration should be visible. This validates activity visibility; it does not diagnose why a real application query is slow.

## Scenario 3 — Open transaction / idle in transaction

Run in one session:

```sql
BEGIN;
SELECT 1;
```

After the `SELECT` completes, leave the transaction open. Refresh diagnostics and inspect the session state / transaction age. Then clean up:

```sql
ROLLBACK;
```

An open transaction is a clue to investigate, not proof of a fault by itself.

## Scenario 4 — Connection pressure (manual investigation exercise)

Do not attempt to exhaust the server. Open a small number of additional local sessions, then compare the current-database connection count with the configured connection limit and other evidence. This version's connection count is scoped to the current database and should not be presented as a complete server-wide exhaustion detector. For a future implementation, collect `pg_stat_activity` grouped by database, user, state and application name, and compare server-wide usage against `max_connections` with proper privileges.

## Scenario 5 — Replication lag (design exercise; not implemented as a detector)

A valid replication-lag investigation requires a primary/standby lab and queries such as `pg_stat_replication` on the primary, plus replay/receive state on the standby. This repository does not currently implement a full replication-lag detector. Do not claim it does until code and a reproducible two-node test are added.

## What to record for each demo

- Scenario name and local timestamp.
- Symptom you deliberately created.
- Expected evidence.
- What the dashboard showed.
- Independent SQL verification result.
- Cleanup performed.
- Limitations or unexpected results.
