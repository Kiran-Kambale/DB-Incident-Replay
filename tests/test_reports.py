from incident_intelligence.reports import build_incident_report


def test_report_labels_observation_as_hypothesis_and_discloses_sampling_limits():
    incident = {
        "id": "abc12345", "title": "Sessions waiting on database locks", "db_name": "incident_intelligence_lab",
        "severity": "warning", "status": "resolved", "first_seen": "2026-11-07T10:00:00+00:00",
        "last_seen": "2026-11-07T10:00:10+00:00", "observation_count": 2,
        "summary": "A blocked session was sampled.", "kind": "lock_wait",
        "details": {"blocked_session_count": 1, "sessions": [{"pid": 101, "state": "active", "blocking_pids": [99], "wait_event_type": "Lock", "wait_event": "transactionid", "application_name": "test-app"}]},
    }
    sample = {
        "captured_at": "2026-11-07T10:00:10+00:00", "server_version": "17.0", "active_sessions": 1,
        "total_client_backends": 2, "max_connections": 100, "lock_waiters": 1,
        "idle_in_transaction": 0, "visibility": {"has_pg_read_all_stats": True},
        "detections": [{"kind": "lock_wait", "details": {"sessions": [{"pid": 101}]}}],
        "stats": {"stats_reset": None},
    }
    report = build_incident_report(incident, [sample], capture_query_text=False)
    assert "hypotheses (not confirmed root causes)" in report
    assert "Sampling can miss events" in report
    assert "SQL text capture is disabled" in report
    assert "blocker" in report.lower()


def test_report_includes_investigation_timeline_comparison_hypotheses_and_impact():
    incident = {
        "id": "abc12345", "title": "Sessions waiting on database locks", "db_name": "incident_lab",
        "severity": "warning", "status": "resolved", "first_seen": "2026-11-07T10:00:00+00:00",
        "last_seen": "2026-11-07T10:00:10+00:00", "observation_count": 2, "kind": "lock_wait",
        "summary": "A blocked session was sampled.", "details": {},
    }
    analysis = {
        "timeline": [{"timestamp": "2026-11-07T10:00:00+00:00", "title": "Finding first observed", "description": "Blocked PID 2"}],
        "comparison": {"definition": "sampled values", "periods": {name: {"sample_count": 1, "metrics": {"active_sessions": {"label": "Active sessions", "observations": 1, "min": 1, "average": 1, "max": 1, "last": 1}}} for name in ("before", "during", "after")}},
        "hypotheses": [{"title": "A lock may have delayed a session.", "classification": "hypothesis", "confidence": "low", "supporting_evidence": ["Blocked PID 2"], "missing_or_alternative_evidence": ["App impact unknown"], "next_checks": ["Check logs"]}],
        "coverage": {"before_samples": 1, "during_samples": 1, "after_samples": 1, "estimated_interval_seconds": 10, "notes": ["Application traces not integrated."], "collection_gaps": []},
        "impact_assessment": {"status": "not_measured", "message": "No application telemetry."},
    }
    report = build_incident_report(incident, [], False, analysis)
    assert "Incident timeline" in report
    assert "Before / during / after comparison" in report
    assert "Evidence-backed investigation hypotheses" in report
    assert "Business impact assessment" in report
    assert "No application telemetry" in report


def test_report_includes_cross_layer_scope_and_application_context():
    from incident_intelligence.reports import build_incident_report

    incident = {
        "id": "report-cross-layer", "title": "Lock wait", "db_name": "incident_lab",
        "severity": "warning", "status": "resolved", "first_seen": "2026-11-07T10:00:00+00:00",
        "last_seen": "2026-11-07T10:00:10+00:00", "observation_count": 2,
        "kind": "lock_wait", "summary": "A lock wait was sampled.", "details": {"blocked_session_count": 1},
    }
    analysis = {
        "cross_layer_context": {
            "host_context": {"cpu_percent": {"average": 44.0, "max": 91.0, "observations": 2},
                             "memory_percent": {"average": 70.0, "max": 71.0, "observations": 2},
                             "disk_percent": {"average": 60.0, "max": 60.0, "observations": 2}},
            "cross_layer_signals": [{"name": "Elevated collector-host CPU", "detail": "CPU reached 91%.",
                                      "classification": "temporal_context_not_causation"}],
            "observed_applications": [{"application_name": "checkout-api", "peak_sessions": 6,
                                       "peak_active_sessions": 4, "peak_lock_waiters": 1, "pids": [101, 202]}],
            "application_context_note": "Application names are contextual metadata.",
        },
        "timeline": [], "comparison": {"definition": "sampled", "periods": {}},
        "hypotheses": [], "coverage": {},
        "impact_assessment": {"status": "not_measured", "message": "Not measured."},
    }
    report = build_incident_report(incident, [], False, analysis)
    assert "## Cross-layer context" in report
    assert "collector host only" in report
    assert "checkout-api" in report
    assert "not proof of causation" in report.lower()
