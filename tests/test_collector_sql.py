from incident_intelligence.collector import METRICS_SQL, SESSIONS_SQL


def test_parameterized_session_query_uses_only_psycopg_placeholders():
    # A percent sign in a psycopg parameterized query is parsed as placeholder
    # syntax. Avoid LIKE wildcards here so only the intended %s remains.
    assert "CASE WHEN %s THEN left(query, 2000)" in SESSIONS_SQL
    assert "LIKE" not in SESSIONS_SQL
    assert "%%" not in SESSIONS_SQL
    assert "idle in transaction" in SESSIONS_SQL


def test_metrics_query_has_no_percent_placeholder_syntax():
    # METRICS_SQL is executed without parameters. Keep it free of percent signs
    # too, which makes future parameterization safe and avoids ambiguity.
    assert "%" not in METRICS_SQL
    assert "idle in transaction" in METRICS_SQL
