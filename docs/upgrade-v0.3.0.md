# Upgrade to PostgreSQL Incident Intelligence v0.3.0

This update builds on v0.2.0 and adds collector-host resource context, PostgreSQL application workload summaries, recurring incident patterns, and a redesigned dashboard.

## Before upgrading

1. Stop the running app with `Ctrl+C`.
2. Back up `.env`.
3. Back up the SQLite evidence database using SQLite's backup API (recommended) or copy it while the application is stopped.
4. Keep the existing project directory and virtual environment until the new version has been verified.

Example SQLite backup while the application is stopped:

```bash
python - <<'PY'
import sqlite3
from pathlib import Path
source_path = Path("data/incident_intelligence.sqlite3")
backup_path = Path("../incident_intelligence_v02_backup.sqlite3")
with sqlite3.connect(source_path) as source, sqlite3.connect(backup_path) as backup:
    source.backup(backup)
print(f"Backup written to {backup_path.resolve()}")
PY
```

## Apply the update

1. Extract `PostgreSQL_Incident_Intelligence_v0.3.0.zip` to a new folder, or overwrite only the project code files in your existing folder.
2. Do not replace `.env`, `data/incident_intelligence.sqlite3`, or your `.venv` folder.
3. Activate your existing virtual environment and install updated requirements:

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
```

4. Start the app:

```bash
python -m incident_intelligence
```

5. Open `http://127.0.0.1:8000` and confirm the database connection and previous incident history are present.

## New capabilities

- Application workload summary based on PostgreSQL `pg_stat_activity.application_name`.
- Collector-host CPU, memory, root-disk utilization and disk read/write rates via `psutil`.
- Cross-layer incident context in the incident investigation view and Markdown RCA report.
- Seven-day recurrence summaries derived from distinct stored incident records.
- Responsive operations dashboard with PostgreSQL activity trend, host resource context, application workload, recurring patterns, incident queue and evidence feed.

## Important telemetry boundary

Host metrics refer to the machine running the Incident Intelligence collector. If the PostgreSQL server is remote, these metrics do not represent the database server's CPU, memory or disk. The dashboard and incident analysis state this limitation explicitly. Remote database-host metrics require a separate authorized agent or integration with an existing host monitoring system.

## Data compatibility

The SQLite schema update adds two columns to the existing `samples` table: `host_metrics_json` and `application_summary_json`. The migration is additive. Existing samples and incident rows are retained; legacy samples receive empty defaults for the new fields. Do not delete the evidence database as part of this update.
