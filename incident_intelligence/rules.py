from __future__ import annotations

from typing import Any


def _finding(kind: str, db_name: str, title: str, severity: str, summary: str, details: dict[str, Any]) -> dict[str, Any]:
    return {
        "fingerprint": f"{db_name}:{kind}",
        "kind": kind,
        "title": title,
        "severity": severity,
        "summary": summary,
        "details": details,
    }


def evaluate_snapshot(snapshot: dict[str, Any], previous_stats: dict[str, Any] | None, settings: Any) -> list[dict[str, Any]]:
    """Rule-based findings. Findings describe observations, not proven root causes."""
    findings: list[dict[str, Any]] = []
    db = snapshot["db_name"]
    sessions = snapshot.get("sessions", [])

    max_conn = int(snapshot.get("max_connections") or 0)
    used = int(snapshot.get("total_client_backends") or 0)
    if max_conn > 0:
        pct = used / max_conn * 100
        if pct >= settings.connection_warning_pct:
            severity = "critical" if pct >= settings.connection_critical_pct else "warning"
            findings.append(_finding(
                "connection_pressure", db, "High connection-slot utilization", severity,
                f"{used} client backends are visible against max_connections={max_conn} ({pct:.1f}%). This is a capacity warning, not proof that new connections were rejected.",
                {"used_connections": used, "max_connections": max_conn, "utilization_pct": round(pct, 1)},
            ))

    blocked = [s for s in sessions if s.get("blocking_pids")]
    if blocked:
        findings.append(_finding(
            "lock_wait", db, "Sessions waiting on database locks", "high" if len(blocked) >= 3 else "warning",
            f"{len(blocked)} sampled client session(s) were waiting on locks. The blocker and affected transaction must be inspected before assigning root cause.",
            {"blocked_session_count": len(blocked), "sessions": blocked[:20]},
        ))

    long_queries = [s for s in sessions if s.get("state") == "active" and int(s.get("query_age_seconds") or 0) >= settings.long_query_seconds]
    if long_queries:
        findings.append(_finding(
            "long_query", db, "Active queries exceeded the configured duration threshold", "warning",
            f"{len(long_queries)} active session(s) had been running for at least {settings.long_query_seconds} seconds when sampled. Duration alone does not establish that a query is unhealthy.",
            {"threshold_seconds": settings.long_query_seconds, "sessions": long_queries[:20]},
        ))

    idle_tx = [s for s in sessions if str(s.get("state") or "").startswith("idle in transaction") and int(s.get("xact_age_seconds") or 0) >= settings.idle_transaction_seconds]
    if idle_tx:
        findings.append(_finding(
            "idle_in_transaction", db, "Transactions remained idle while open", "high" if len(idle_tx) >= 3 else "warning",
            f"{len(idle_tx)} session(s) were idle in a transaction for at least {settings.idle_transaction_seconds} seconds. Such sessions can retain locks and delay cleanup, depending on workload and transaction state.",
            {"threshold_seconds": settings.idle_transaction_seconds, "sessions": idle_tx[:20]},
        ))

    lag = snapshot.get("max_replica_lag_bytes")
    replicas = int(snapshot.get("streaming_replicas") or 0)
    if not snapshot.get("is_in_recovery") and replicas > 0 and lag is not None and int(lag) >= settings.replication_lag_warning_bytes:
        findings.append(_finding(
            "replication_lag", db, "Streaming replica replay lag exceeded threshold", "warning",
            f"The largest sampled primary-to-replica replay distance was {int(lag):,} bytes across {replicas} streaming replica(s). This is an LSN distance, not a direct time-based lag measurement.",
            {"replica_count": replicas, "max_replica_lag_bytes": int(lag), "threshold_bytes": settings.replication_lag_warning_bytes},
        ))

    current_stats = snapshot.get("stats", {})
    if previous_stats and current_stats.get("stats_reset") == previous_stats.get("stats_reset"):
        previous_deadlocks = int(previous_stats.get("deadlocks") or 0)
        current_deadlocks = int(current_stats.get("deadlocks") or 0)
        delta = current_deadlocks - previous_deadlocks
        if delta > 0:
            findings.append(_finding(
                "deadlock_increase", db, "PostgreSQL deadlock counter increased", "warning",
                f"The pg_stat_database deadlock counter increased by {delta} between two successful samples. This counter does not identify the individual transactions involved.",
                {"deadlock_delta": delta, "counter_total": current_deadlocks},
            ))
    return findings
