from incident_intelligence.investigation import build_incident_analysis


def make_incident(kind="lock_wait"):
    return {
        "id": "test-incident", "kind": kind, "title": "Sessions waiting on locks",
        "db_name": "incident_intelligence_lab", "severity": "warning", "status": "resolved",
        "first_seen": "2026-11-07T10:00:10+00:00", "last_seen": "2026-11-07T10:00:20+00:00",
        "closed_at": "2026-11-07T10:00:30+00:00", "observation_count": 2,
        "summary": "One session was blocked.",
        "details": {"blocked_session_count": 1, "sessions": [{"pid": 202, "blocking_pids": [101]}]},
    }


def sample(ts, connections, detections=None, sessions=None):
    return {
        "id": int(ts[-2:]), "captured_at": ts, "db_name": "incident_intelligence_lab",
        "server_version": "17.0", "total_client_backends": connections,
        "max_connections": 100, "active_sessions": connections // 2,
        "idle_sessions": connections // 2, "idle_in_transaction": 0,
        "lock_waiters": 1 if detections else 0, "database_size_bytes": 1024,
        "max_replica_lag_bytes": None, "streaming_replicas": 0,
        "stats": {}, "pgss": [], "visibility": {"query_text_captured": False},
        "sessions": sessions or [], "detections": detections or [],
    }


def test_incident_analysis_splits_before_during_after_and_calculates_comparison():
    incident = make_incident()
    finding = {"kind": "lock_wait", "summary": "A lock wait was sampled.", "details": {"sessions": [{"pid": 202, "blocking_pids": [101]}]}}
    samples = [
        sample("2026-11-07T10:00:00+00:00", 10),
        sample("2026-11-07T10:00:10+00:00", 30, [finding]),
        sample("2026-11-07T10:00:20+00:00", 40, [finding]),
        sample("2026-11-07T10:00:30+00:00", 12),
    ]
    analysis = build_incident_analysis(incident, samples)
    periods = analysis["comparison"]["periods"]
    assert periods["before"]["sample_count"] == 1
    assert periods["during"]["sample_count"] == 2
    assert periods["after"]["sample_count"] == 1
    assert periods["during"]["metrics"]["total_client_backends"]["average"] == 35
    assert any(event["event_type"] == "first_observed" for event in analysis["timeline"])
    assert any(event["event_type"] == "resolved" for event in analysis["timeline"])


def test_lock_hypothesis_uses_blocking_pid_evidence_and_keeps_uncertainty():
    incident = make_incident()
    finding = {"kind": "lock_wait", "summary": "Blocked session sampled.", "details": {"sessions": [{"pid": 202, "blocking_pids": [101]}]}}
    sample_during = sample(
        "2026-11-07T10:00:10+00:00", 20, [finding],
        sessions=[
            {"pid": 202, "state": "active", "blocking_pids": [101], "wait_event_type": "Lock", "wait_event": "transactionid"},
            {"pid": 101, "state": "idle in transaction", "xact_age_seconds": 85, "blocking_pids": []},
        ],
    )
    analysis = build_incident_analysis(incident, [sample_during])
    hypothesis = analysis["hypotheses"][0]
    assert hypothesis["classification"] == "hypothesis"
    assert hypothesis["confidence"] == "medium"
    assert any("101" in item for item in hypothesis["supporting_evidence"])
    assert any("not directly measured" in item for item in hypothesis["missing_or_alternative_evidence"])


def test_missing_baseline_and_post_samples_are_disclosed():
    incident = make_incident("long_query")
    finding = {"kind": "long_query", "summary": "Long query.", "details": {"sessions": []}}
    analysis = build_incident_analysis(incident, [sample("2026-11-07T10:00:10+00:00", 5, [finding])])
    assert analysis["coverage"]["before_samples"] == 0
    assert analysis["coverage"]["after_samples"] == 0
    assert any("No pre-incident baseline" in note for note in analysis["coverage"]["notes"])
    assert any("No post-incident sample" in note for note in analysis["coverage"]["notes"])
    assert analysis["impact_assessment"]["status"] == "not_measured"


def test_blocker_pid_is_not_joined_across_different_samples():
    incident = make_incident()
    finding = {"kind": "lock_wait", "summary": "Blocked session sampled.", "details": {"sessions": [{"pid": 202, "blocking_pids": [101]}]}}
    blocked_sample = sample("2026-11-07T10:00:10+00:00", 20, [finding], sessions=[
        {"pid": 202, "state": "active", "blocking_pids": [101], "wait_event_type": "Lock"},
    ])
    other_sample = sample("2026-11-07T10:00:20+00:00", 20, sessions=[
        {"pid": 101, "state": "idle in transaction", "xact_age_seconds": 500},
    ])
    analysis = build_incident_analysis(incident, [blocked_sample, other_sample])
    basis = " ".join(analysis["hypotheses"][0]["supporting_evidence"])
    assert "Blocker session details captured in the same sample" not in basis
