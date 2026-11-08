from incident_intelligence.collector import APPLICATION_SQL


def test_application_summary_query_groups_sessions_by_application_name():
    assert "GROUP BY" in APPLICATION_SQL
    assert "application_name" in APPLICATION_SQL
    assert "lock_waiters" in APPLICATION_SQL
    assert "idle_in_transaction" in APPLICATION_SQL
    assert "%s" not in APPLICATION_SQL
    assert "LIKE" not in APPLICATION_SQL
