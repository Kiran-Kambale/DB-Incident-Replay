from pathlib import Path

from incident_intelligence.investigation import build_incident_analysis
from incident_intelligence.store import EvidenceStore


def base_snapshot(timestamp: str) -> dict:
    return {
        "captured_at": timestamp, "db_name": "incident_intelligence_lab", "server_version": "17.0",
        "is_in_recovery": False, "max_connections": 100, "total_client_backends": 12,
        "active_sessions": 4, "idle_sessions": 8, "idle_in_transaction": 0, "lock_waiters": 1,
        "database_size_bytes": 1024, "streaming_replicas": 0, "max_replica_lag_bytes": None,
        "stats": {}, "sessions": [], "pgss": [], "visibility": {"has_pg_read_all_stats": True},
        "host_metrics": {"available": True, "scope": "collector_host_only", "cpu_percent": 91.0,
                         "memory_percent": 92.0, "disk_percent": 45.0, "hostname": "test-host"},
        "application_summary": [{"application_name": "checkout-api", "total_sessions": 5,
                                 "active_sessions": 3, "lock_waiters": 1,
                                 "idle_in_transaction": 0, "max_query_age_seconds": 42}],
    }


def test_store_migrates_old_schema_and_preserves_existing_samples(tmp_path: Path):
    import sqlite3
    db = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE samples (id INTEGER PRIMARY KEY AUTOINCREMENT, captured_at TEXT NOT NULL, db_name TEXT NOT NULL, server_version TEXT, is_in_recovery INTEGER NOT NULL DEFAULT 0, max_connections INTEGER, total_client_backends INTEGER, active_sessions INTEGER, idle_sessions INTEGER, idle_in_transaction INTEGER, lock_waiters INTEGER, database_size_bytes INTEGER, streaming_replicas INTEGER, max_replica_lag_bytes INTEGER, stats_json TEXT NOT NULL, sessions_json TEXT NOT NULL, pgss_json TEXT NOT NULL, detections_json TEXT NOT NULL, visibility_json TEXT NOT NULL)")
        conn.execute("INSERT INTO samples(captured_at,db_name,stats_json,sessions_json,pgss_json,detections_json,visibility_json) VALUES(?,?,?,?,?,?,?)",
                     ("2026-11-07T10:00:00+00:00", "legacy_db", "{}", "[]", "[]", "[]", "{}"))
    store = EvidenceStore(db)
    existing = store.latest_sample()
    assert existing["db_name"] == "legacy_db"
    assert existing["host_metrics"] == {}
    assert existing["application_summary"] == []
    store.persist_sample(base_snapshot("2026-11-07T10:00:10+00:00"), [])
    latest = store.latest_sample()
    assert latest["host_metrics"]["hostname"] == "test-host"
    assert latest["application_summary"][0]["application_name"] == "checkout-api"


def test_incident_pattern_aggregation_is_based_on_stored_incident_rows(tmp_path: Path):
    store = EvidenceStore(tmp_path / "patterns.sqlite3")
    finding = {"fingerprint": "incident_intelligence_lab:lock_wait", "kind": "lock_wait",
               "title": "Sessions waiting on database locks", "severity": "warning",
               "summary": "A lock wait was observed.", "details": {"blocked_session_count": 1}}
    store.persist_sample(base_snapshot("2026-11-07T10:00:00+00:00"), [finding])
    store.persist_sample(base_snapshot("2026-11-07T10:00:10+00:00"), [finding])
    patterns = store.incident_patterns(days=7)
    assert patterns[0]["kind"] == "lock_wait"
    assert patterns[0]["incident_count"] == 1
    assert patterns[0]["observation_count"] == 2
    assert patterns[0]["open_count"] == 1


def test_cross_layer_context_shows_app_and_host_as_context_not_cause():
    incident = {
        "id": "i1", "kind": "lock_wait", "title": "Lock wait", "db_name": "incident_intelligence_lab",
        "severity": "warning", "status": "open", "first_seen": "2026-11-07T10:00:10+00:00",
        "last_seen": "2026-11-07T10:00:10+00:00", "observation_count": 1,
        "summary": "One session is waiting on a lock.",
    }
    sample = base_snapshot("2026-11-07T10:00:10+00:00")
    sample["detections"] = [{"kind": "lock_wait", "summary": "Lock wait", "details": {"sessions": [
        {"pid": 202, "application_name": "checkout-api", "blocking_pids": [101], "query_age_seconds": 42}
    ]}}]
    analysis = build_incident_analysis(incident, [sample])
    context = analysis["cross_layer_context"]
    assert context["observed_applications"][0]["application_name"] == "checkout-api"
    assert context["host_context"]["cpu_percent"]["max"] == 91.0
    assert context["cross_layer_signals"][0]["classification"] == "temporal_context_not_causation"
    assert "not PostgreSQL-server metrics" in context["host_context"]["note"]
    assert analysis["comparison"]["periods"]["during"]["metrics"]["host_cpu_percent"]["max"] == 91.0


def test_host_sampler_returns_explicit_scope_and_stable_schema():
    from incident_intelligence.host_metrics import HostMetricsSampler

    sampler = HostMetricsSampler()
    first = sampler.collect()
    second = sampler.collect()
    assert first["scope"] == "collector_host_only"
    assert "available" in first
    if first["available"]:
        assert first["hostname"]
        assert 0 <= first["memory_percent"] <= 100
        assert 0 <= first["disk_percent"] <= 100
        # CPU is intentionally unavailable on the first non-blocking sample.
        assert first["cpu_percent"] is None
        assert second["cpu_percent"] is None or 0 <= second["cpu_percent"] <= 100
