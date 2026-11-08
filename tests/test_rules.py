from types import SimpleNamespace

from incident_intelligence.rules import evaluate_snapshot


SETTINGS = SimpleNamespace(
    connection_warning_pct=80.0,
    connection_critical_pct=95.0,
    long_query_seconds=30,
    idle_transaction_seconds=60,
    replication_lag_warning_bytes=100_000_000,
)


def base_snapshot():
    return {
        "db_name": "incident_lab",
        "max_connections": 100,
        "total_client_backends": 10,
        "is_in_recovery": False,
        "streaming_replicas": 0,
        "max_replica_lag_bytes": None,
        "stats": {"stats_reset": "2026-11-01 00:00:00+00", "deadlocks": 0},
        "sessions": [],
    }


def test_no_finding_for_healthy_snapshot():
    assert evaluate_snapshot(base_snapshot(), None, SETTINGS) == []


def test_connection_pressure_is_warning_not_root_cause():
    snapshot = base_snapshot()
    snapshot["total_client_backends"] = 85
    findings = evaluate_snapshot(snapshot, None, SETTINGS)
    assert [f["kind"] for f in findings] == ["connection_pressure"]
    assert findings[0]["severity"] == "warning"
    assert "not proof" in findings[0]["summary"]


def test_lock_wait_uses_blocking_pid_evidence():
    snapshot = base_snapshot()
    snapshot["sessions"] = [{"pid": 12, "state": "active", "blocking_pids": [10], "wait_event_type": "Lock"}]
    findings = evaluate_snapshot(snapshot, None, SETTINGS)
    assert findings[0]["kind"] == "lock_wait"
    assert findings[0]["details"]["sessions"][0]["blocking_pids"] == [10]


def test_long_query_threshold_is_applied():
    snapshot = base_snapshot()
    snapshot["sessions"] = [{"pid": 12, "state": "active", "query_age_seconds": 45, "blocking_pids": []}]
    findings = evaluate_snapshot(snapshot, None, SETTINGS)
    assert any(f["kind"] == "long_query" for f in findings)


def test_idle_transaction_threshold_is_applied():
    snapshot = base_snapshot()
    snapshot["sessions"] = [{"pid": 12, "state": "idle in transaction", "xact_age_seconds": 90, "blocking_pids": []}]
    findings = evaluate_snapshot(snapshot, None, SETTINGS)
    assert any(f["kind"] == "idle_in_transaction" for f in findings)


def test_deadlock_alert_requires_same_stats_reset_epoch():
    snapshot = base_snapshot()
    snapshot["stats"]["deadlocks"] = 3
    previous = {"stats_reset": "2026-11-01 00:00:00+00", "deadlocks": 1}
    findings = evaluate_snapshot(snapshot, previous, SETTINGS)
    assert any(f["kind"] == "deadlock_increase" for f in findings)
    reset_previous = {"stats_reset": "2026-10-01 00:00:00+00", "deadlocks": 1}
    assert not any(f["kind"] == "deadlock_increase" for f in evaluate_snapshot(snapshot, reset_previous, SETTINGS))
