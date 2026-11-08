# MVP validation matrix

| Capability | Implementation in v0.3.0 | How to validate | Known limitation |
|---|---|---|---|
| Real PostgreSQL connection | Psycopg connection using `DATABASE_URL` | Connect to `incident_lab`; inspect collector status | Environment/network specific |
| Read-only collection | `default_transaction_read_only=on`; SELECT-only collector queries | Inspect `pg_stat_activity` for application name; verify app cannot perform business writes | Session-level SET is used to enforce read-only behaviour |
| Historical evidence | Periodic samples stored in SQLite | Wait 2–3 minutes; inspect timeline and `/api/evidence` | No pre-installation history; interval can miss brief events |
| Connection pressure | Visible client backends divided by `max_connections` | Controlled low-capacity test cluster | Ratio is a warning indicator, not proof of connection failures |
| Lock wait | `wait_event_type='Lock'` and `pg_blocking_pids(pid)` | Two-session row lock test | Visibility depends on PostgreSQL privileges and sample timing |
| Long query | Active query age threshold | `SELECT pg_sleep(45)` | Long duration alone is not proof of poor performance |
| Idle transaction | Transaction age threshold | Begin, SELECT, leave transaction open | Impact depends on locks, snapshots and workload |
| Deadlock counter | Difference in `pg_stat_database.deadlocks` across samples | Controlled two-session deadlock | Counter does not identify SQL or specific transactions |
| Replication replay distance | `pg_wal_lsn_diff(primary current LSN, replica replay LSN)` | Primary with a streaming standby | Byte distance is not time lag; standby sampling is not included in this initial rule |
| Incident lifecycle | Open/update/resolve per database/rule fingerprint | Trigger and then clear each test condition | A condition not observed in a successful sample is treated as no longer active |
| RCA report | Markdown facts, coverage, hypotheses and checks | Download report for each test | Not a confirmed root-cause analysis |
| Optional pg_stat_statements | Top cumulative statements when enabled | Install/enable extension and grant access | Cumulative view, not historical per-execution event capture |
| Incident timeline | Retained baseline, incident-observation, post-period and rule-clearance events | Trigger and resolve each test; inspect event timestamps | Cannot reconstruct events never sampled; rule clearance is not proof of business recovery |
| Before/during/after comparison | Compares sampled connection, active/idle, lock, transaction, database size and replica byte-distance metrics | Ensure at least one sample exists in each period | Uses last sampled value per period; no interpolation or continuous measurement |
| Investigation hypotheses | Rule-specific deterministic hypothesis with supporting and missing evidence | Inspect lock, long-query, idle-transaction, connection and deadlock cases | Hypotheses require DBA verification; no automatic causation claim |
| Collection coverage | Sample counts, estimated cadence, gaps, baseline/post samples and query-text capture status | Pause collector briefly or test before first/after last observations | Estimated cadence is inferred from available samples |
| Business impact disclosure | Marks impact as not measured without application/business telemetry | Inspect incident workspace and report | No user/request/revenue impact quantification in v0.2.0 |
| RCA investigation export | Markdown report with timeline, comparison, hypotheses, coverage and next checks | Download report from incident detail | Human review required before customer distribution |

| Collector-host resource context | `psutil` captures CPU, memory, root-volume utilization and disk I/O rates | Keep the local collector running for several samples; inspect host panel and incident comparison | Metrics describe the collector machine only; not the remote database host unless independently verified |
| Application workload attribution | `pg_stat_activity` grouped by `application_name` | Connect test clients with distinct `application_name` values; compare dashboard groups with `pg_stat_activity` | Application names are client-supplied labels; do not identify end-user impact or prove causation |
| Cross-layer incident context | Application and collector-host signals aligned to samples triggering a finding | Trigger a lock wait from a named application and inspect incident detail/RCA | Temporal correlation only; host metrics are not server metrics unless host identity is verified |
| Recurring patterns | Distinct incident records grouped by rule kind over seven days | Trigger, resolve, and re-trigger the same rule after the previous incident closes | Continuous observations within one incident are not counted as separate incidents |
| Additive SQLite upgrade | Adds `host_metrics_json` and `application_summary_json` columns when missing | Run tests against a legacy schema and confirm existing rows remain | Back up the SQLite file before any upgrade as standard practice |
| Responsive operations dashboard | Overview, activity trend, host panel, application table, recurrence list, incident queue and evidence history | Inspect at desktop and mobile viewport sizes; test incident modal and report download | UI remains a local single-user MVP; no authentication or multi-tenant controls |
