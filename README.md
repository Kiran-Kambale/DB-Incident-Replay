# PostgreSQL Incident Intelligence

**Local MVP — version 0.3.0**

A local-first PostgreSQL incident evidence collector and investigation dashboard. It connects to a real PostgreSQL database using a read-only session, samples live database activity, stores snapshots in a separate local SQLite evidence store, detects a small set of operational conditions, and generates a Markdown incident report.

This is deliberately an evidence-first MVP. It does not claim to prove root cause automatically.

## Installation

You can run PostgreSQL Incident Intelligence using either of the following methods:

- **Option 1: Docker Installation** – Recommended for quick setup. No need to install Python, PostgreSQL, or application dependencies manually.
- **Option 2: Manual Installation** – Set up the application and PostgreSQL environment yourself.

---

### Option 1: Docker Installation (Recommended)

The easiest way to get started is with Docker Compose. It automatically starts the application and its PostgreSQL database.

**Prerequisites**

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running.
- Git installed (if cloning the repository).

**Step 1: Clone the repository**

```bash
git clone https://github.com/Kiran-Kambale/DB-Incident-Replay.git
cd DB-Incident-Replay
```

**Step 2: Configure your credentials**

Open `docker-compose.yml`.

Update the PostgreSQL password in both places:

```yaml
POSTGRES_PASSWORD: ChangeThisPassword123!
```

And in the application's database connection string:

```yaml
DATABASE_URL: postgresql://postgres:ChangeThisPassword123!@db:5432/incident_lab
```

Use the same strong, unique password in both places.

**Step 3: Start the application**

Run:

```bash
docker compose -f docker-compose.yml up -d 

```

Docker Compose will download the required images, create the containers, configure the network, and start the application and PostgreSQL database.

**Step 4: Open the dashboard**

Once the containers are running, open:

**http://localhost:8000**

That's it! PostgreSQL Incident Intelligence is ready for local evaluation.

**Useful Docker Commands**

| Command | Purpose |
|---|---|
| `docker compose ps` | Check container status |
| `docker compose logs -f app` | View application logs |
| `docker compose logs -f db` | View PostgreSQL logs |
| `docker compose restart` | Restart services |
| `docker compose stop` | Stop services |
| `docker compose up -d` | Start services again |
| `docker compose down` | Stop and remove containers |

**Important:** Your incident history and PostgreSQL data are stored in Docker volumes. Do not use `docker compose down -v` unless you intentionally want to delete those volumes and their data.

---

### Option 2: Manual Installation

---

## Requirements

- Python 3.10+ (Python 3.12 is a good choice).
- PostgreSQL 12+ recommended. The first development target is PostgreSQL 17.
- A PostgreSQL role that can connect to the target database and preferably is a member of the built-in `pg_monitor` role.

## 1. Create a dedicated local test database

Do not run the deliberately blocking test scenarios against production. Create a disposable database for this product:

```bash
# Create this isolated test database once (skip createdb if it already exists).
createdb incident_lab
psql -d incident_lab -f sql/create_test_lab.sql
```

If your local PostgreSQL service is not running, start it first. On a Homebrew installation, the service name depends on the installed major version; for example:

```bash
brew services list
brew services start postgresql@17
```

Confirm the server and database are available:

```bash
psql -d incident_lab -c "SELECT version(), current_database(), current_user;"
```

## 2. Create a monitoring login (recommended)

Use a separate account rather than a personal application login. Run the following as a PostgreSQL administrator, replacing the sample password with a strong local password:

```sql
CREATE ROLE incident_monitor LOGIN PASSWORD 'REPLACE_WITH_A_STRONG_PASSWORD';
GRANT pg_monitor TO incident_monitor;
GRANT CONNECT ON DATABASE incident_lab TO incident_monitor;
```

The built-in `pg_monitor` role provides monitoring/statistics visibility. It does not make the login a superuser and is not a grant to modify application tables. Review PostgreSQL's role documentation and your organization's access policy before granting it in any shared environment.

For a local-only test, you can use your existing local superuser. The collector still forces its own PostgreSQL session into read-only mode, but a dedicated monitoring login is a better test of intended deployment permissions.

## 3. Configure the connection

From this project directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and set `DATABASE_URL`. Example:

```dotenv
DATABASE_URL=postgresql://incident_monitor:YOUR_PASSWORD@127.0.0.1:5432/incident_lab
```

If your local PostgreSQL uses a different username, password, port or authentication method, change the URL accordingly. Do not commit `.env` to Git; it is ignored by `.gitignore`.

Recommended initial settings:

```dotenv
COLLECT_INTERVAL_SECONDS=10
LONG_QUERY_SECONDS=30
IDLE_TRANSACTION_SECONDS=60
CONNECTION_WARNING_PCT=80
CONNECTION_CRITICAL_PCT=95
CAPTURE_QUERY_TEXT=false
ENABLE_PG_STAT_STATEMENTS=false
```

**Privacy default:** SQL text is not saved. The product can still detect query duration and lock waits from metadata. Enable `CAPTURE_QUERY_TEXT=true` only in a controlled environment after considering whether SQL may contain personal data, literals, tokens or other sensitive values. SQL text is saved in the local SQLite evidence database when enabled.

## 4. Start the product

After configuring `.env`, run the launcher (it creates the virtual environment and installs requirements if needed):

```bash
chmod +x start.sh
./start.sh
```

Or, with the virtual environment already active:

```bash
python -m incident_intelligence
```

Open:

```text
http://127.0.0.1:8000
```

The collector begins sampling automatically. The first snapshot appears after a successful connection. Keep this terminal running while you create test scenarios in other terminals.

The API documentation is available locally at:

```text
http://127.0.0.1:8000/docs
```

## 5. Run real incident scenarios

Open separate terminals and connect each one to `incident_intelligence_lab` using `psql`. Follow [`docs/test-scenarios.md`](docs/test-scenarios.md) in order:

1. Long-running query: `SELECT pg_sleep(45);`
2. Idle in transaction: `BEGIN;` then a `SELECT`, leave it open for over 60 seconds.
3. Blocking transaction: Session A updates account 1 and remains uncommitted; Session B updates the same row and waits.
4. Optional controlled connection pressure and deadlock tests.

Expected product behaviour:

- The incident appears after a sample observes the configured condition.
- The incident records first-seen, last-seen and observation count.
- The incident resolves after a later successful sample no longer observes that condition.
- Clicking a finding opens its captured details.
- The Markdown RCA report distinguishes observed evidence from hypotheses.

Do not expect the product to show evidence for a test that completed between collection polls. Increase sampling frequency for a controlled test if needed, while keeping the collection load reasonable.

## 6. Incident investigation workspace (v0.2.0 foundation)

Click an incident in the table to open its investigation workspace. It now includes:

- **What we know:** the original rule summary and captured session details.
- **Incident timeline:** nearby baseline samples, each sampled rule observation, samples where the rule was not detected, and the rule-clearance timestamp when resolved.
- **Before / during / after:** the last sampled value for each metric in each period, plus sample counts. The comparison uses retained snapshots, not a continuous measurement.
- **Investigation hypotheses:** deterministic rule-specific possibilities, each labeled as a hypothesis with supporting evidence, missing or alternative evidence, and recommended next checks.
- **Evidence coverage:** counts of samples in each period, estimated sample cadence, collection gaps, and query-text capture state.
- **Business impact:** explicitly marked not measured because application traces, user/request outcomes and business telemetry are not integrated yet.

Download the Markdown RCA report from the same workspace. It includes the timeline, comparison, hypotheses, evidence gaps and impact limitation.

The timeline only shows events that were actually captured. A condition not detected in a later sample means that rule did not trigger in that sample; it does not prove the application issue was resolved. A blocker PID is correlated to blocker-session details only within the same sample to avoid incorrectly joining a reused PostgreSQL PID from another time.

## 7. Recommended test sequence

Start with defaults. Run the long query, idle transaction and blocking-session scenarios one at a time. For each test:

1. Record the time you start the test.
2. Wait until the finding appears.
3. Open the finding and verify the observed PID, state, threshold and blockers where relevant.
4. Stop the test cleanly (`ROLLBACK` for open transactions).
5. Wait for the incident to resolve.
6. Download its Markdown report and inspect evidence coverage and limitations.

For a proper validation exercise, compare the dashboard's observations with `pg_stat_activity`, `pg_blocking_pids()` and PostgreSQL logs from the same time.

## 8. Data and privacy

- PostgreSQL is queried; the product does not create or modify application tables.
- The collector uses an explicitly read-only PostgreSQL session and a short statement timeout.
- The local SQLite store contains operational metadata, timestamps, session identifiers, application names and rule details. Query text is omitted by default.
- `CAPTURE_QUERY_TEXT=true` and optional `pg_stat_statements` text capture can persist SQL text locally. Treat the SQLite file as potentially sensitive if either is enabled.
- The web application binds to `127.0.0.1`, not all network interfaces. Do not expose it to a network without adding authentication, TLS, CSRF protection, tenant isolation and a security review.
- The `.env` file contains credentials and must remain private.

## 9. Configuration

| Variable | Default | Meaning |
|---|---:|---|
| `DATABASE_URL` | empty | PostgreSQL connection URL |
| `COLLECT_INTERVAL_SECONDS` | `10` | Sample interval; values below 5 are raised to 5 |
| `LONG_QUERY_SECONDS` | `30` | Active query duration threshold |
| `IDLE_TRANSACTION_SECONDS` | `60` | Idle-in-transaction age threshold |
| `CONNECTION_WARNING_PCT` | `80` | Connection-slot warning threshold |
| `CONNECTION_CRITICAL_PCT` | `95` | Critical connection-slot threshold |
| `REPLICATION_LAG_WARNING_BYTES` | `104857600` | Replay distance threshold (100 MiB) on a primary |
| `CAPTURE_QUERY_TEXT` | `false` | Opt-in SQL text persistence |
| `ENABLE_PG_STAT_STATEMENTS` | `false` | Opt-in top cumulative statement sampling |
| `EVIDENCE_DB_PATH` | `./data/incident_intelligence.sqlite3` | Local evidence database path |

## 10. Development checks

```bash
pytest -q
python -m compileall -q incident_intelligence tests
```

The automated suite covers detection rules, incident persistence, the investigation analysis, report export and the detail/report API handlers. It does not replace integration tests against your own PostgreSQL server.

## 11. Troubleshooting

**Connection refused** — confirm PostgreSQL is running, host and port are correct, and the database exists.

**Password authentication failed** — verify the role password and `pg_hba.conf` authentication method. Do not weaken authentication globally just to make the MVP connect.

**Limited visibility warning** — use a dedicated role and grant membership in `pg_monitor` according to your security policy. Without sufficient statistics privileges, PostgreSQL may hide other users' query/session details.

**No incident appears** — confirm the target `.env` points to the database used by your test sessions, wait for the configured threshold plus one collection interval, and check the collector status banner. Historical evidence starts only after the app connects.

**Optional pg_stat_statements unavailable** — the extension must be installed and loaded according to PostgreSQL's `shared_preload_libraries` requirements, created in the connected database, and readable by the monitoring role. This optional feature does not stop the main collector.

**Reset the local evidence store** — stop the app and remove `data/incident_intelligence.sqlite3` (and its `-wal` / `-shm` files if present). This permanently deletes local captured history and incidents.

## Architecture

```text
PostgreSQL (read-only sampling)
  ├─ pg_stat_activity / pg_blocking_pids
  ├─ pg_stat_database
  ├─ pg_stat_replication (primary only)
  └─ optional pg_stat_statements
          |
          v
Python collector + deterministic detection rules
          |
          v
Local SQLite evidence store
          |
          v
FastAPI + local dashboard + Markdown incident reports
```

This is a validation MVP, not a production-ready commercial platform. Before customer deployment, add authentication, tenant isolation, managed secrets, encrypted evidence storage, collector health monitoring, retention controls, structured database-log ingestion, application/host integrations, backup/restore validation, load testing and a formal security review.


## PostgreSQL documentation used for the collector design

- [PostgreSQL 17 — Monitoring Database Activity](https://www.postgresql.org/docs/17/monitoring-stats.html): `pg_stat_activity`, dynamic statistics and `pg_read_all_stats` visibility.
- [PostgreSQL 17 — pg_stat_statements](https://www.postgresql.org/docs/17/pgstatstatements.html): extension loading, cumulative statement statistics and query identifiers.
- [PostgreSQL 17 — Predefined Roles](https://www.postgresql.org/docs/17/predefined-roles.html): privileges provided by `pg_monitor`.


## v0.3.0 — Cross-layer operational context

The v0.3.0 release extends the v0.2.0 incident investigation workspace. It includes:

- Lightweight collector-host CPU, memory, root-volume usage and disk I/O rate samples (using `psutil`). These describe the machine running this collector only; they are not represented as PostgreSQL server metrics unless host identity is independently verified.
- Application workload summaries grouped by PostgreSQL `application_name`, including session, active-session, lock-wait and idle-in-transaction counts. Application names are client-supplied labels and are not guaranteed to identify a service uniquely.
- Cross-layer incident context that aligns application and collector-host observations with samples that triggered a rule. Temporal overlap is contextual evidence, not proof of causation.
- Seven-day recurring incident pattern summaries based on distinct stored incident records.
- Additive SQLite migrations for the new telemetry fields. Existing incident history is retained; older samples display empty host/application context.
- An upgraded operations dashboard with activity charts, collector-host resource panels, application workloads, recurrence summaries, incident work queue and detailed investigation views.

### Host telemetry boundary

The collector runs on the same machine as the FastAPI application. If PostgreSQL is remote, `psutil` values describe the collector machine, not the database server. To obtain database-server CPU, memory and disk telemetry for a remote PostgreSQL host, install a separate authorized host agent or integrate an existing host-monitoring API. This release does not claim to collect remote database-host metrics.

### v0.3.0 update

See [`docs/upgrade-v0.3.0.md`](docs/upgrade-v0.3.0.md). The upgrade is additive and does not require deleting the local SQLite database. Back up `.env` and `data/incident_intelligence.sqlite3` before replacing code. Install the updated Python requirements so `psutil` is available.
