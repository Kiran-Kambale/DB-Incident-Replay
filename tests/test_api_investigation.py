import asyncio

from incident_intelligence import main


class FakeStore:
    def __init__(self):
        self.item = {
            "id": "test-incident", "fingerprint": "lab:lock_wait", "kind": "lock_wait",
            "db_name": "incident_intelligence_lab", "title": "Sessions waiting on locks",
            "severity": "warning", "status": "resolved",
            "first_seen": "2026-11-07T10:00:10+00:00", "last_seen": "2026-11-07T10:00:10+00:00",
            "closed_at": "2026-11-07T10:00:20+00:00", "summary": "A blocked session was sampled.",
            "observation_count": 1, "details": {"blocked_session_count": 1,
                "sessions": [{"pid": 202, "blocking_pids": [101]}]},
        }
        self.samples = [
            {"id": 1, "captured_at": "2026-11-07T10:00:00+00:00", "db_name": "incident_intelligence_lab",
             "total_client_backends": 8, "max_connections": 100, "active_sessions": 2,
             "idle_sessions": 6, "idle_in_transaction": 0, "lock_waiters": 0,
             "database_size_bytes": 1024, "max_replica_lag_bytes": None,
             "stats": {}, "sessions": [], "detections": [], "visibility": {"query_text_captured": False}},
            {"id": 2, "captured_at": "2026-11-07T10:00:10+00:00", "db_name": "incident_intelligence_lab",
             "total_client_backends": 12, "max_connections": 100, "active_sessions": 4,
             "idle_sessions": 8, "idle_in_transaction": 0, "lock_waiters": 1,
             "database_size_bytes": 1024, "max_replica_lag_bytes": None,
             "stats": {}, "sessions": [], "visibility": {"query_text_captured": False},
             "detections": [{"kind": "lock_wait", "summary": "A blocked session was sampled.",
                 "details": {"sessions": [{"pid": 202, "blocking_pids": [101]}]}}]},
            {"id": 3, "captured_at": "2026-11-07T10:00:20+00:00", "db_name": "incident_intelligence_lab",
             "total_client_backends": 9, "max_connections": 100, "active_sessions": 2,
             "idle_sessions": 7, "idle_in_transaction": 0, "lock_waiters": 0,
             "database_size_bytes": 1024, "max_replica_lag_bytes": None,
             "stats": {}, "sessions": [], "detections": [], "visibility": {"query_text_captured": False}},
        ]

    def get_incident(self, incident_id):
        return self.item if incident_id == self.item["id"] else None

    def samples_for_incident(self, first_seen, last_seen, padding_seconds=30, closed_at=None):
        return self.samples


def test_incident_detail_api_includes_investigation_payload(monkeypatch):
    monkeypatch.setattr(main, "store", FakeStore())
    result = asyncio.run(main.incident_detail("test-incident"))
    assert "analysis" in result
    assert len(result["analysis"]["timeline"]) >= 2
    assert result["analysis"]["comparison"]["periods"]["before"]["sample_count"] == 1
    assert result["analysis"]["comparison"]["periods"]["after"]["sample_count"] == 1


def test_incident_report_api_exports_investigation_analysis(monkeypatch):
    monkeypatch.setattr(main, "store", FakeStore())
    response = asyncio.run(main.incident_report("test-incident"))
    body = response.body.decode("utf-8")
    assert response.media_type == "text/markdown"
    assert "Before / during / after comparison" in body
    assert "Evidence-backed investigation hypotheses" in body
    assert "Business impact assessment" in body


class FakeAnalyticsStore:
    def recent_samples(self, limit):
        return [{
            "captured_at": "2026-11-07T10:00:00+00:00",
            "host_metrics": {"available": True, "hostname": "dev-host", "cpu_percent": 12.5,
                             "memory_percent": 42.0, "disk_percent": 63.0},
            "application_summary": [{"application_name": "checkout-api", "total_sessions": 4,
                                     "active_sessions": 2, "lock_waiters": 0}],
        }]

    def incident_patterns(self, days, limit):
        return [{"kind": "lock_wait", "title": "Sessions waiting on locks", "incident_count": 2,
                 "open_count": 1, "observation_count": 5, "last_seen": "2026-11-07T10:00:00+00:00"}]


def test_analytics_api_returns_host_scope_apps_and_patterns(monkeypatch):
    monkeypatch.setattr(main, "store", FakeAnalyticsStore())
    result = asyncio.run(main.analytics())
    assert result["host_latest"]["hostname"] == "dev-host"
    assert result["applications"][0]["application_name"] == "checkout-api"
    assert result["incident_patterns_7d"][0]["incident_count"] == 2
    assert "not PostgreSQL server metrics" in result["scope_note"]
