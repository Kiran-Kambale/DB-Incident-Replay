from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from typing import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def json_dumps(value: Any) -> str:
    return json.dumps(value, default=str, separators=(",", ":"))


class EvidenceStore:
    """Local SQLite evidence store. PostgreSQL is only read by the collector."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=15000")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_db(self) -> None:
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    captured_at TEXT NOT NULL,
                    db_name TEXT NOT NULL,
                    server_version TEXT,
                    is_in_recovery INTEGER NOT NULL DEFAULT 0,
                    max_connections INTEGER,
                    total_client_backends INTEGER,
                    active_sessions INTEGER,
                    idle_sessions INTEGER,
                    idle_in_transaction INTEGER,
                    lock_waiters INTEGER,
                    database_size_bytes INTEGER,
                    streaming_replicas INTEGER,
                    max_replica_lag_bytes INTEGER,
                    stats_json TEXT NOT NULL,
                    sessions_json TEXT NOT NULL,
                    pgss_json TEXT NOT NULL,
                    detections_json TEXT NOT NULL,
                    visibility_json TEXT NOT NULL,
                    host_metrics_json TEXT NOT NULL DEFAULT '{}',
                    application_summary_json TEXT NOT NULL DEFAULT '[]'
                );
                CREATE INDEX IF NOT EXISTS idx_samples_captured_at ON samples(captured_at);
                CREATE TABLE IF NOT EXISTS incidents (
                    id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    db_name TEXT NOT NULL,
                    title TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    status TEXT NOT NULL,
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL,
                    closed_at TEXT,
                    summary TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    observation_count INTEGER NOT NULL DEFAULT 1
                );
                CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents(status, last_seen);
                CREATE INDEX IF NOT EXISTS idx_incidents_fingerprint ON incidents(fingerprint, status);
                """
            )
            # Additive migrations preserve existing v0.1/v0.2 incident history.
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(samples)").fetchall()}
            if "host_metrics_json" not in columns:
                conn.execute("ALTER TABLE samples ADD COLUMN host_metrics_json TEXT NOT NULL DEFAULT '{}' ")
            if "application_summary_json" not in columns:
                conn.execute("ALTER TABLE samples ADD COLUMN application_summary_json TEXT NOT NULL DEFAULT '[]' ")

    def latest_sample(self) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM samples ORDER BY id DESC LIMIT 1").fetchone()
        return self._sample_row(row) if row else None

    def latest_stats(self) -> dict[str, Any] | None:
        sample = self.latest_sample()
        return sample.get("stats") if sample else None

    def persist_sample(self, snapshot: dict[str, Any], detections: list[dict[str, Any]]) -> int:
        captured_at = snapshot["captured_at"]
        with self.connect() as conn:
            cursor = conn.execute(
                """INSERT INTO samples (
                    captured_at, db_name, server_version, is_in_recovery,
                    max_connections, total_client_backends, active_sessions, idle_sessions,
                    idle_in_transaction, lock_waiters, database_size_bytes,
                    streaming_replicas, max_replica_lag_bytes, stats_json, sessions_json,
                    pgss_json, detections_json, visibility_json, host_metrics_json, application_summary_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    captured_at, snapshot["db_name"], snapshot["server_version"],
                    int(snapshot["is_in_recovery"]), snapshot["max_connections"],
                    snapshot["total_client_backends"], snapshot["active_sessions"],
                    snapshot["idle_sessions"], snapshot["idle_in_transaction"],
                    snapshot["lock_waiters"], snapshot["database_size_bytes"],
                    snapshot["streaming_replicas"], snapshot["max_replica_lag_bytes"],
                    json_dumps(snapshot.get("stats", {})), json_dumps(snapshot.get("sessions", [])),
                    json_dumps(snapshot.get("pgss", [])), json_dumps(detections),
                    json_dumps(snapshot.get("visibility", {})),
                    json_dumps(snapshot.get("host_metrics", {})), json_dumps(snapshot.get("application_summary", [])),
                ),
            )
            sample_id = int(cursor.lastrowid)
            active_fingerprints: set[str] = set()
            for finding in detections:
                fingerprint = finding["fingerprint"]
                active_fingerprints.add(fingerprint)
                existing = conn.execute(
                    "SELECT id FROM incidents WHERE fingerprint=? AND status='open' ORDER BY first_seen DESC LIMIT 1",
                    (fingerprint,),
                ).fetchone()
                if existing:
                    conn.execute(
                        """UPDATE incidents SET last_seen=?, severity=?, summary=?, details_json=?,
                           observation_count=observation_count+1 WHERE id=?""",
                        (captured_at, finding["severity"], finding["summary"], json_dumps(finding["details"]), existing["id"]),
                    )
                else:
                    conn.execute(
                        """INSERT INTO incidents (
                            id, fingerprint, kind, db_name, title, severity, status,
                            first_seen, last_seen, summary, details_json, observation_count
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,1)""",
                        (
                            str(uuid.uuid4()), fingerprint, finding["kind"], snapshot["db_name"],
                            finding["title"], finding["severity"], "open", captured_at,
                            captured_at, finding["summary"], json_dumps(finding["details"]),
                        ),
                    )
            # Only resolve incidents after a successful collection/evaluation.
            open_rows = conn.execute("SELECT id, fingerprint FROM incidents WHERE status='open'").fetchall()
            for row in open_rows:
                if row["fingerprint"] not in active_fingerprints:
                    conn.execute(
                        "UPDATE incidents SET status='resolved', closed_at=? WHERE id=?",
                        (captured_at, row["id"]),
                    )
        return sample_id

    def list_incidents(self, status: str = "all", limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as conn:
            if status in {"open", "resolved"}:
                rows = conn.execute(
                    "SELECT * FROM incidents WHERE status=? ORDER BY last_seen DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM incidents ORDER BY last_seen DESC LIMIT ?", (limit,)).fetchall()
        return [self._incident_row(row) for row in rows]

    def get_incident(self, incident_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM incidents WHERE id=?", (incident_id,)).fetchone()
        return self._incident_row(row) if row else None

    def samples_for_incident(self, first_seen: str, last_seen: str, padding_seconds: int = 30, closed_at: str | None = None) -> list[dict[str, Any]]:
        try:
            start = datetime.fromisoformat(first_seen).timestamp() - padding_seconds
            end_anchor = max(last_seen, closed_at) if closed_at else last_seen
            end = datetime.fromisoformat(end_anchor).timestamp() + padding_seconds
            start_iso = datetime.fromtimestamp(start, timezone.utc).isoformat(timespec="seconds")
            end_iso = datetime.fromtimestamp(end, timezone.utc).isoformat(timespec="seconds")
        except (ValueError, TypeError):
            start_iso, end_iso = first_seen, last_seen
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM samples WHERE captured_at BETWEEN ? AND ? ORDER BY captured_at ASC",
                (start_iso, end_iso),
            ).fetchall()
        return [self._sample_row(row) for row in rows]

    def recent_samples(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM samples ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [self._sample_row(row) for row in reversed(rows)]

    def incident_patterns(self, days: int = 7, limit: int = 8) -> list[dict[str, Any]]:
        """Return recurrence patterns from stored incident records, not guesses."""
        cutoff = datetime.now(timezone.utc).timestamp() - max(1, days) * 86400
        cutoff_iso = datetime.fromtimestamp(cutoff, timezone.utc).isoformat(timespec="seconds")
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT kind, title, count(*) AS incident_count,
                          sum(CASE WHEN status='open' THEN 1 ELSE 0 END) AS open_count,
                          sum(observation_count) AS observation_count,
                          max(last_seen) AS last_seen,
                          sum(CASE WHEN severity IN ('high','critical') THEN 1 ELSE 0 END) AS high_severity_count
                   FROM incidents WHERE first_seen >= ?
                   GROUP BY kind, title ORDER BY incident_count DESC, last_seen DESC LIMIT ?""",
                (cutoff_iso, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def counts(self) -> dict[str, int]:
        with self.connect() as conn:
            samples = conn.execute("SELECT count(*) AS n FROM samples").fetchone()["n"]
            open_incidents = conn.execute("SELECT count(*) AS n FROM incidents WHERE status='open'").fetchone()["n"]
            total_incidents = conn.execute("SELECT count(*) AS n FROM incidents").fetchone()["n"]
        return {"samples": int(samples), "open_incidents": int(open_incidents), "total_incidents": int(total_incidents)}

    @staticmethod
    def _sample_row(row: sqlite3.Row) -> dict[str, Any]:
        if row is None:
            return {}
        item = dict(row)
        for source, target in (("stats_json", "stats"), ("sessions_json", "sessions"),
                               ("pgss_json", "pgss"), ("detections_json", "detections"),
                               ("visibility_json", "visibility"), ("host_metrics_json", "host_metrics"),
                               ("application_summary_json", "application_summary")):
            item[target] = json.loads(item.pop(source) or ("[]" if target in {"sessions", "pgss", "detections"} else "{}"))
        return item

    @staticmethod
    def _incident_row(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["details"] = json.loads(item.pop("details_json") or "{}")
        return item
