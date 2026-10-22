# 5-Minute Portfolio Demo Script

## 0:00–0:45 — Problem

“PostgreSQL support investigations often begin with symptoms and fragmented evidence. I built DB Incident Replay as a local-first prototype to make current diagnostic evidence and repeatable incident tests easier to inspect.”

## 0:45–1:30 — Architecture

Show the README architecture: browser UI → FastAPI API → local PostgreSQL. Explain that credentials stay server-side and the app uses a dedicated reader role for the lab.

## 1:30–3:00 — Reproduce a real lock

Run Session A's uncommitted update and Session B's update to the same row. Show Session B waiting. Click Run diagnostics and point out the blocker PID, blocked PID and wait information.

## 3:00–4:00 — Validate independently

Run the `pg_blocking_pids()` verification query in a third session. Compare its output with the dashboard. Explain that independent verification is important and findings are evidence, not a guaranteed root cause.

## 4:00–4:30 — Resolve

Commit Session A. Show Session B finishing and the blocking relationship disappearing after refreshing the dashboard.

## 4:30–5:00 — Limitations and roadmap

Explain that the prototype detects current state and does not yet persist historical snapshots. The next milestone is timestamped evidence and incident history. State that it is a local demo and not production-ready.
