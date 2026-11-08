import json
from pathlib import Path
from types import SimpleNamespace

from incident_intelligence.store import EvidenceStore


def test_persists_sample_and_opens_then_resolves_incident(tmp_path: Path):
    store = EvidenceStore(tmp_path / "test.sqlite3")
    snapshot = {
        "captured_at": "2026-11-07T10:00:00+00:00", "db_name": "incident_lab", "server_version": "17.0",
        "is_in_recovery": False, "max_connections": 100, "total_client_backends": 90,
        "active_sessions": 2, "idle_sessions": 88, "idle_in_transaction": 0, "lock_waiters": 0,
        "database_size_bytes": 1024, "streaming_replicas": 0, "max_replica_lag_bytes": None,
        "stats": {"deadlocks": 0}, "sessions": [], "pgss": [], "visibility": {"has_pg_read_all_stats": True},
    }
    finding = {"fingerprint": "incident_lab:connection_pressure", "kind": "connection_pressure", "title": "High connection-slot utilization", "severity": "warning", "summary": "90%", "details": {"utilization_pct": 90}}
    store.persist_sample(snapshot, [finding])
    assert store.counts()["open_incidents"] == 1
    snapshot["captured_at"] = "2026-11-07T10:00:10+00:00"
    store.persist_sample(snapshot, [])
    assert store.counts()["open_incidents"] == 0
    assert store.list_incidents("resolved")[0]["status"] == "resolved"
    assert len(store.recent_samples(10)) == 2


def test_samples_for_incident_extends_context_through_closed_at(tmp_path: Path):
    store = EvidenceStore(tmp_path / "closed-window.sqlite3")
    base = {
        "db_name": "incident_lab", "server_version": "17.0", "is_in_recovery": False,
        "max_connections": 100, "total_client_backends": 5, "active_sessions": 1,
        "idle_sessions": 4, "idle_in_transaction": 0, "lock_waiters": 0,
        "database_size_bytes": 1024, "streaming_replicas": 0, "max_replica_lag_bytes": None,
        "stats": {}, "sessions": [], "pgss": [], "visibility": {},
    }
    for timestamp in (
        "2026-11-07T10:00:00+00:00",
        "2026-11-07T10:00:10+00:00",
        "2026-11-07T10:01:00+00:00",
        "2026-11-07T10:01:10+00:00",
    ):
        store.persist_sample({**base, "captured_at": timestamp}, [])
    rows = store.samples_for_incident(
        "2026-11-07T10:00:10+00:00", "2026-11-07T10:00:10+00:00",
        padding_seconds=5, closed_at="2026-11-07T10:01:00+00:00",
    )
    assert [row["captured_at"] for row in rows] == [
        "2026-11-07T10:00:10+00:00", "2026-11-07T10:01:00+00:00"
    ]
