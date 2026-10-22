# Timestamped evidence and incident history (v0.3)

## What it does

The dashboard's **Capture evidence** action runs current read-only diagnostic queries and saves a point-in-time snapshot with a UTC timestamp. The snapshot includes database name, findings, current blocking relationships, activity rows, connection counts, optional title and notes.

## Run a repeatable test

1. Start the API and open `http://127.0.0.1:8000`.
2. Click **Run diagnostics** to confirm the database connection.
3. In Session A, run `BEGIN;` and update `demo_accounts.account_id = 1`, leaving the transaction open.
4. In Session B, update the same row so the query waits.
5. In the dashboard, enter a title such as `LAB-001 blocking before commit`; add a note that this is a synthetic row-lock test; click **Capture evidence**.
6. Under **Incident history**, click **Refresh history**, then **View** on the snapshot. Verify that the saved findings include a blocking relationship and that blocker/blocked PIDs are recorded.
7. In Session A, run `COMMIT;` to release the lock.
8. Capture a second snapshot titled `LAB-001 blocking after commit`.
9. Open both snapshots and compare their timestamps, lock counts and findings. The first should normally show the blocking relationship; the second should normally show no current blocking after Session B completes.

## API endpoints

- `POST /api/history/capture` with optional JSON body `{"title":"LAB-001","notes":"Synthetic lock test"}`
- `GET /api/history` lists the latest 100 snapshots.
- `GET /api/history/{snapshot_id}` returns a stored snapshot.

## Local storage

Snapshots are stored in `data/incident_history.sqlite3`, relative to the project root. The file is created automatically on application start and excluded from Git. Back it up only if needed, and treat it as sensitive because SQL text and connection metadata may be included.

## Important limitations

- Capture is manual; no background or scheduled collection is implemented.
- A snapshot describes the state observed at capture time; it cannot recreate events that were not recorded.
- PID values can be reused by PostgreSQL over time; do not use a PID alone as a durable incident identity.
- The current prototype has no authentication or multi-user access controls. Keep it bound to `127.0.0.1`.
- Review and redact SQL text or notes before sharing a screenshot, report, or history database.
