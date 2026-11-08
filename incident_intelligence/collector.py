from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .config import Settings
from .host_metrics import HostMetricsSampler
from .rules import evaluate_snapshot
from .state import collector_state
from .store import EvidenceStore


METRICS_SQL = """
SELECT
  extract(epoch FROM clock_timestamp())::double precision AS captured_epoch,
  current_database() AS db_name,
  current_setting('server_version') AS server_version,
  current_setting('max_connections')::integer AS max_connections,
  pg_is_in_recovery() AS is_in_recovery,
  count(*) FILTER (WHERE backend_type = 'client backend')::integer AS total_client_backends,
  count(*) FILTER (WHERE backend_type = 'client backend' AND state = 'active')::integer AS active_sessions,
  count(*) FILTER (WHERE backend_type = 'client backend' AND state = 'idle')::integer AS idle_sessions,
  count(*) FILTER (WHERE backend_type = 'client backend' AND left(state, 19) = 'idle in transaction')::integer AS idle_in_transaction,
  count(*) FILTER (WHERE backend_type = 'client backend' AND wait_event_type = 'Lock')::integer AS lock_waiters,
  pg_database_size(current_database())::bigint AS database_size_bytes,
  CASE WHEN pg_is_in_recovery() THEN 0 ELSE (SELECT count(*) FROM pg_stat_replication)::integer END AS streaming_replicas,
  CASE WHEN pg_is_in_recovery() THEN NULL ELSE (SELECT max(pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn))::bigint FROM pg_stat_replication) END AS max_replica_lag_bytes
FROM pg_stat_activity
WHERE pid <> pg_backend_pid()
"""

SESSIONS_SQL = """
SELECT
  pid, datname, usename, application_name,
  COALESCE(client_addr::text, 'local') AS client_addr,
  backend_type, state, wait_event_type, wait_event,
  CASE WHEN query_start IS NULL THEN NULL ELSE extract(epoch FROM (clock_timestamp() - query_start))::integer END AS query_age_seconds,
  CASE WHEN xact_start IS NULL THEN NULL ELSE extract(epoch FROM (clock_timestamp() - xact_start))::integer END AS xact_age_seconds,
  pg_blocking_pids(pid) AS blocking_pids,
  CASE WHEN %s THEN left(query, 2000) ELSE NULL END AS query_text
FROM pg_stat_activity
WHERE pid <> pg_backend_pid()
  AND backend_type = 'client backend'
  AND (state = 'active' OR left(state, 19) = 'idle in transaction' OR wait_event_type = 'Lock')
ORDER BY COALESCE(query_start, xact_start) NULLS LAST
LIMIT 100
"""

STATS_SQL = """
SELECT stats_reset::text AS stats_reset,
       xact_commit::bigint AS xact_commit,
       xact_rollback::bigint AS xact_rollback,
       blks_read::bigint AS blks_read,
       blks_hit::bigint AS blks_hit,
       tup_returned::bigint AS tup_returned,
       tup_fetched::bigint AS tup_fetched,
       deadlocks::bigint AS deadlocks,
       temp_files::bigint AS temp_files,
       temp_bytes::bigint AS temp_bytes
FROM pg_stat_database
WHERE datname = current_database()
"""

APPLICATION_SQL = """
SELECT
  COALESCE(NULLIF(application_name, ''), '(unnamed client)') AS application_name,
  count(*)::integer AS total_sessions,
  count(*) FILTER (WHERE state = 'active')::integer AS active_sessions,
  count(*) FILTER (WHERE wait_event_type = 'Lock')::integer AS lock_waiters,
  count(*) FILTER (WHERE left(state, 19) = 'idle in transaction')::integer AS idle_in_transaction,
  max(CASE WHEN query_start IS NULL THEN NULL ELSE extract(epoch FROM (clock_timestamp() - query_start))::integer END) AS max_query_age_seconds
FROM pg_stat_activity
WHERE pid <> pg_backend_pid() AND backend_type = 'client backend'
GROUP BY COALESCE(NULLIF(application_name, ''), '(unnamed client)')
ORDER BY count(*) DESC, application_name
LIMIT 12
"""

VISIBILITY_SQL = """
SELECT current_user AS connected_user,
       pg_has_role(current_user, 'pg_read_all_stats', 'MEMBER') AS has_pg_read_all_stats,
       (SELECT count(*) FROM pg_stat_activity) AS visible_activity_rows,
       (SELECT count(*) FROM pg_stat_activity WHERE backend_type='client backend') AS visible_client_backends
"""


class PostgresCollector:
    def __init__(self, settings: Settings, store: EvidenceStore) -> None:
        self.settings = settings
        self.store = store
        self.host_sampler = HostMetricsSampler()

    def collect_once(self) -> dict[str, Any]:
        collector_state.attempted()
        if not self.settings.database_url:
            message = "DATABASE_URL is empty. Copy .env.example to .env and configure your PostgreSQL connection."
            collector_state.update(connected=False, last_error=message)
            raise RuntimeError(message)

        try:
            import psycopg
            from psycopg.rows import dict_row

            # Session is forced read-only and statements have short timeouts.
            with psycopg.connect(
                self.settings.database_url,
                connect_timeout=5,
                application_name="postgresql_incident_intelligence",
                options="-c default_transaction_read_only=on -c statement_timeout=5000 -c lock_timeout=2000 -c timezone=UTC",
                row_factory=dict_row,
                autocommit=True,
            ) as conn:
                metrics = conn.execute(METRICS_SQL).fetchone()
                sessions = conn.execute(SESSIONS_SQL, (self.settings.capture_query_text,)).fetchall()
                stats = conn.execute(STATS_SQL).fetchone() or {}
                visibility = conn.execute(VISIBILITY_SQL).fetchone() or {}
                application_summary = [dict(row) for row in conn.execute(APPLICATION_SQL).fetchall()]
                pgss, pgss_note = self._collect_pgss(conn)
                captured = datetime.fromtimestamp(float(metrics["captured_epoch"]), timezone.utc).isoformat(timespec="seconds")
                snapshot: dict[str, Any] = {
                    "captured_at": captured,
                    "db_name": metrics["db_name"],
                    "server_version": metrics["server_version"],
                    "is_in_recovery": bool(metrics["is_in_recovery"]),
                    "max_connections": int(metrics["max_connections"]),
                    "total_client_backends": int(metrics["total_client_backends"]),
                    "active_sessions": int(metrics["active_sessions"]),
                    "idle_sessions": int(metrics["idle_sessions"]),
                    "idle_in_transaction": int(metrics["idle_in_transaction"]),
                    "lock_waiters": int(metrics["lock_waiters"]),
                    "database_size_bytes": int(metrics["database_size_bytes"]),
                    "streaming_replicas": int(metrics["streaming_replicas"] or 0),
                    "max_replica_lag_bytes": int(metrics["max_replica_lag_bytes"]) if metrics["max_replica_lag_bytes"] is not None else None,
                    "stats": dict(stats),
                    "sessions": [self._normalize_session(dict(row)) for row in sessions],
                    "pgss": pgss,
                    "application_summary": application_summary,
                    "host_metrics": self.host_sampler.collect(),
                    "visibility": {**dict(visibility), "pg_stat_statements_note": pgss_note,
                                   "query_text_captured": self.settings.capture_query_text},
                }

            previous_stats = self.store.latest_stats()
            detections = evaluate_snapshot(snapshot, previous_stats, self.settings)
            self.store.persist_sample(snapshot, detections)
            collector_state.update(
                connected=True,
                last_success_at=captured,
                last_error=None,
                database=snapshot["db_name"],
                server_version=snapshot["server_version"],
                collector_pid=None,
            )
            return {"captured_at": captured, "db_name": snapshot["db_name"], "detections": detections}
        except Exception as exc:
            collector_state.update(connected=False, last_error=f"{type(exc).__name__}: {exc}")
            raise

    def _collect_pgss(self, conn: Any) -> tuple[list[dict[str, Any]], str]:
        if not self.settings.enable_pg_stat_statements:
            return [], "Disabled. Set ENABLE_PG_STAT_STATEMENTS=true to enable optional query-statistics sampling."
        try:
            installed = conn.execute("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname='pg_stat_statements') AS installed").fetchone()["installed"]
            if not installed:
                return [], "pg_stat_statements is not installed in the connected database."
            major_row = conn.execute("SELECT current_setting('server_version_num')::integer AS version_num").fetchone()
            major = int(major_row["version_num"]) // 10000
            time_col = "total_exec_time" if major >= 13 else "total_time"
            mean_col = "mean_exec_time" if major >= 13 else "mean_time"
            query_sql = f"""SELECT queryid::text AS queryid, calls::bigint AS calls,
                {time_col}::double precision AS total_time_ms,
                {mean_col}::double precision AS mean_time_ms,
                rows::bigint AS rows, shared_blks_hit::bigint AS shared_blks_hit,
                shared_blks_read::bigint AS shared_blks_read,
                CASE WHEN %s THEN left(query, 1000) ELSE NULL END AS query_text
                FROM pg_stat_statements ORDER BY {time_col} DESC LIMIT 10"""
            rows = conn.execute(query_sql, (self.settings.capture_query_text,)).fetchall()
            return [dict(row) for row in rows], f"Collected top {len(rows)} cumulative statements; counters are since pg_stat_statements reset, not per-execution history."
        except Exception as exc:
            # Optional feature must never stop the primary telemetry collector.
            return [], f"Optional collection unavailable: {type(exc).__name__}: {exc}"

    @staticmethod
    def _normalize_session(row: dict[str, Any]) -> dict[str, Any]:
        for key in ("query_start", "xact_start"):
            if row.get(key) is not None:
                row[key] = row[key].isoformat()
            row.pop(key, None)
        row["blocking_pids"] = list(row.get("blocking_pids") or [])
        return row
