from __future__ import annotations

from datetime import datetime, timezone
from statistics import median
from typing import Any


METRICS: tuple[tuple[str, str], ...] = (
    ("total_client_backends", "Client connections"),
    ("active_sessions", "Active sessions"),
    ("idle_sessions", "Idle sessions"),
    ("idle_in_transaction", "Idle-in-transaction sessions"),
    ("lock_waiters", "Lock waiters"),
    ("max_replica_lag_bytes", "Maximum replica replay distance (bytes)"),
    ("database_size_bytes", "Database size (bytes)"),
    ("host_cpu_percent", "Collector-host CPU (%)"),
    ("host_memory_percent", "Collector-host memory (%)"),
    ("host_disk_percent", "Collector-host root disk (%)"),
)


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed
    except (TypeError, ValueError):
        return None


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if result == result and abs(result) != float("inf") else None
    except (TypeError, ValueError):
        return None


def _sample_periods(incident: dict[str, Any], samples: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    first = _parse_time(incident.get("first_seen"))
    last = _parse_time(incident.get("last_seen"))
    periods: dict[str, list[dict[str, Any]]] = {"before": [], "during": [], "after": []}
    for sample in samples:
        captured = _parse_time(sample.get("captured_at"))
        if not captured or not first or not last:
            continue
        if captured < first:
            periods["before"].append(sample)
        elif captured <= last:
            periods["during"].append(sample)
        else:
            periods["after"].append(sample)
    return periods


def _summarize_period(samples: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {"sample_count": len(samples), "metrics": {}}
    for key, label in METRICS:
        def read_metric(sample: dict[str, Any]) -> float | None:
            if key.startswith("host_"):
                host_key = key.removeprefix("host_")
                return _number((sample.get("host_metrics") or {}).get(host_key))
            return _number(sample.get(key))
        values = [value for sample in samples if (value := read_metric(sample)) is not None]
        summary["metrics"][key] = {
            "label": label,
            "min": min(values) if values else None,
            "average": round(sum(values) / len(values), 2) if values else None,
            "max": max(values) if values else None,
            "last": values[-1] if values else None,
            "observations": len(values),
        }
    return summary


def _timeline(incident: dict[str, Any], samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kind = incident.get("kind")
    first_seen = incident.get("first_seen")
    last_seen = incident.get("last_seen")
    first = _parse_time(first_seen)
    last = _parse_time(last_seen)
    events: list[dict[str, Any]] = []

    before = [s for s in samples if (t := _parse_time(s.get("captured_at"))) and first and t < first]
    after = [s for s in samples if (t := _parse_time(s.get("captured_at"))) and last and t > last]
    # A few surrounding samples make context readable without dumping every poll.
    for sample in before[-3:]:
        events.append({
            "timestamp": sample["captured_at"], "event_type": "baseline",
            "title": "Baseline sample", "description": _sample_description(sample),
            "sample_id": sample.get("id"),
        })

    for sample in samples:
        matches = [d for d in sample.get("detections", []) if d.get("kind") == kind]
        if not matches:
            continue
        finding = matches[0]
        event_type = "first_observed" if sample.get("captured_at") == first_seen else "observed_again"
        events.append({
            "timestamp": sample["captured_at"], "event_type": event_type,
            "title": "Finding first observed" if event_type == "first_observed" else "Finding observed again",
            "description": finding.get("summary") or incident.get("summary", "Condition detected in sample."),
            "sample_id": sample.get("id"),
        })

    for sample in after[:3]:
        events.append({
            "timestamp": sample["captured_at"], "event_type": "not_observed",
            "title": "Condition not detected in this sample",
            "description": _sample_description(sample), "sample_id": sample.get("id"),
        })

    if incident.get("status") == "resolved" and incident.get("closed_at"):
        events.append({
            "timestamp": incident["closed_at"], "event_type": "resolved",
            "title": "Condition no longer detected",
            "description": "A successful collection no longer triggered this incident rule. This confirms rule clearance in the sample, not that the underlying business issue was resolved.",
            "sample_id": None,
        })

    order = {"baseline": 0, "first_observed": 1, "observed_again": 2, "not_observed": 3, "resolved": 4}
    events.sort(key=lambda e: (_parse_time(e["timestamp"]) or datetime.min.replace(tzinfo=timezone.utc), order.get(e["event_type"], 9)))
    return events


def _sample_description(sample: dict[str, Any]) -> str:
    return (
        f"Connections {sample.get('total_client_backends', '—')}/{sample.get('max_connections', '—')}; "
        f"active sessions {sample.get('active_sessions', '—')}; lock waiters {sample.get('lock_waiters', '—')}; "
        f"idle-in-transaction {sample.get('idle_in_transaction', '—')}."
    )


def _session_evidence(incident: dict[str, Any], samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    seen: set[tuple[Any, Any, Any]] = set()
    kind = incident.get("kind")
    for sample in samples:
        for detection in sample.get("detections", []):
            if detection.get("kind") != kind:
                continue
            details = detection.get("details") or {}
            for session in details.get("sessions", []):
                key = (session.get("pid"), sample.get("captured_at"), tuple(session.get("blocking_pids") or []))
                if key in seen:
                    continue
                seen.add(key)
                evidence.append({**session, "sampled_at": sample.get("captured_at")})
    return evidence


def _hypotheses(incident: dict[str, Any], samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kind = incident.get("kind")
    evidence_sessions = _session_evidence(incident, samples)
    hypotheses: list[dict[str, Any]] = []

    def add(title: str, confidence: str, basis: list[str], gaps: list[str], checks: list[str]) -> None:
        hypotheses.append({
            "title": title, "classification": "hypothesis", "confidence": confidence,
            "supporting_evidence": basis, "missing_or_alternative_evidence": gaps,
            "next_checks": checks,
        })

    if kind == "lock_wait":
        blocked_pids = sorted({int(s["pid"]) for s in evidence_sessions if s.get("pid") is not None})
        blocker_pids = sorted({int(pid) for s in evidence_sessions for pid in (s.get("blocking_pids") or [])})
        # Match a blocker PID only to a session captured in the same sample.
        # PostgreSQL PIDs can be reused; cross-sample matching could misattribute a blocker.
        blocker_rows: dict[tuple[str, int], dict[str, Any]] = {}
        for sample in samples:
            sample_time = str(sample.get("captured_at") or "")
            for session in sample.get("sessions", []):
                try:
                    pid = int(session.get("pid"))
                except (TypeError, ValueError):
                    continue
                blocker_rows[(sample_time, pid)] = session
        basis = [f"Blocked session PID(s) observed: {', '.join(map(str, blocked_pids)) or 'not retained'}."]
        if blocker_pids:
            basis.append(f"pg_blocking_pids() reported blocker PID(s): {', '.join(map(str, blocker_pids))}.")
        matched_blockers: list[str] = []
        for blocked_session in evidence_sessions:
            sampled_at = str(blocked_session.get("sampled_at") or "")
            for blocker_pid in blocked_session.get("blocking_pids") or []:
                try:
                    blocker_pid_int = int(blocker_pid)
                except (TypeError, ValueError):
                    continue
                row = blocker_rows.get((sampled_at, blocker_pid_int))
                if row:
                    matched_blockers.append(
                        f"PID {blocker_pid_int} at {sampled_at}: state={row.get('state') or 'unknown'}, "
                        f"transaction age={row.get('xact_age_seconds') if row.get('xact_age_seconds') is not None else 'not captured'}s"
                    )
        if matched_blockers:
            basis.append("Blocker session details captured in the same sample: " + "; ".join(sorted(set(matched_blockers))) + ".")
        add(
            "A blocking transaction may have delayed one or more sessions.",
            "medium" if matched_blockers else "low", basis,
            ["The sampled lock wait may be brief or expected for the workload.", "Application request impact and lock-wait duration were not directly measured.", "A blocker can change or finish between collection intervals."],
            ["Inspect the blocker PID and its transaction age in nearby samples.", "Check pg_locks and PostgreSQL log entries for the same timestamps.", "Correlate the blocked query with application request latency before claiming business impact."],
        )
    elif kind == "connection_pressure":
        details = incident.get("details") or {}
        pct = details.get("utilization_pct", "not recorded")
        used, maximum = details.get("used_connections"), details.get("max_connections")
        add(
            "Connection-slot pressure may have contributed to connection acquisition delays.", "low",
            [f"The rule observed {used if used is not None else 'unknown'} visible client backends against max_connections={maximum if maximum is not None else 'unknown'} ({pct}%)."],
            ["The collector does not capture failed connection attempts or application pool queue depth.", "Reserved connection slots and connections created after the sample may affect usable capacity."],
            ["Inspect application pool active/idle counts and pending acquisition queues.", "Review PostgreSQL connection errors and application timeout logs.", "Check reserved_connections/superuser_reserved_connections where supported by this PostgreSQL version."],
        )
    elif kind == "long_query":
        waits = sorted({f"{s.get('wait_event_type')}/{s.get('wait_event')}" for s in evidence_sessions if s.get("wait_event_type") or s.get("wait_event")})
        pids = sorted({str(s.get("pid")) for s in evidence_sessions if s.get("pid") is not None})
        basis = [f"Active statement PID(s) exceeded the configured duration threshold: {', '.join(pids) or 'not retained'}."]
        if waits:
            basis.append("Wait events sampled: " + ", ".join(waits) + ".")
        add(
            "A long-running statement or a wait encountered by that statement may explain the observed duration.", "low",
            basis,
            ["A long duration is not automatically a performance defect; expected batch or reporting work may run for a long time.", "The product has not established query plan regression, CPU saturation or I/O bottleneck from duration alone."],
            ["Review the query plan with EXPLAIN (ANALYZE, BUFFERS) in a safe representative environment.", "Inspect wait events and resource metrics during the same interval.", "Compare the query's normal execution time and application timeout."],
        )
    elif kind == "idle_in_transaction":
        ages = [int(s.get("xact_age_seconds") or 0) for s in evidence_sessions]
        pids = sorted({str(s.get("pid")) for s in evidence_sessions if s.get("pid") is not None})
        basis = [f"Idle-in-transaction session PID(s): {', '.join(pids) or 'not retained'}."]
        if ages:
            basis.append(f"Maximum sampled transaction age: {max(ages)} seconds.")
        add(
            "An open idle transaction may retain an old snapshot or locks, depending on its activity and isolation level.", "low",
            basis,
            ["The snapshot does not prove that the transaction currently holds a conflicting lock.", "Vacuum delay or table bloat impact was not directly measured."],
            ["Identify the owning application/request and inspect the transaction's age.", "Inspect pg_locks and backend_xmin for the same PID where permissions permit.", "Check vacuum progress and dead-tuple trends before attributing maintenance impact."],
        )
    elif kind == "replication_lag":
        details = incident.get("details") or {}
        add(
            "Replica replay may be falling behind WAL generation or delivery.", "low",
            [f"Sampled primary-to-replica replay distance: {details.get('max_replica_lag_bytes', 'unknown')} bytes across {details.get('replica_count', 'unknown')} replica(s)."],
            ["Byte distance is not a time-based lag measurement.", "No sustained trend, network throughput or standby I/O diagnosis is established by this finding alone."],
            ["Compare WAL generation and replay rates over time.", "Inspect pg_stat_replication write/flush/replay LSNs and replay timestamps.", "Check standby I/O, network throughput and replay conflicts."],
        )
    elif kind == "deadlock_increase":
        details = incident.get("details") or {}
        add(
            "One or more deadlocks occurred between successful database-statistics samples.", "medium",
            [f"The database-wide deadlock counter increased by {details.get('deadlock_delta', 'unknown')}.", f"Counter total at the later sample: {details.get('counter_total', 'unknown')} (subject to stats reset)."],
            ["The cumulative counter does not identify involved PIDs, statements or application transactions.", "The current evidence store may not contain PostgreSQL deadlock log details."],
            ["Inspect PostgreSQL server logs for deadlock reports in the interval.", "Correlate the logged statements and transaction order with application traces.", "Review consistent lock ordering and transaction scope."],
        )
    else:
        add("The detected condition needs additional investigation.", "low", [incident.get("summary", "A rule was triggered.")], ["No specific causal mechanism is established."], ["Review the original sample and relevant PostgreSQL logs."])
    return hypotheses


def _cross_layer_context(incident: dict[str, Any], samples: list[dict[str, Any]]) -> dict[str, Any]:
    kind = incident.get("kind")
    relevant_sessions: list[dict[str, Any]] = []
    relevant_times: set[str] = set()
    for sample in samples:
        for detection in sample.get("detections", []):
            if detection.get("kind") != kind:
                continue
            relevant_times.add(str(sample.get("captured_at")))
            for session in (detection.get("details") or {}).get("sessions", []):
                relevant_sessions.append({**session, "sampled_at": sample.get("captured_at")})

    app_counts: dict[str, dict[str, Any]] = {}
    for sample in samples:
        if str(sample.get("captured_at")) not in relevant_times:
            continue
        for app_row in sample.get("application_summary", []):
            app = str(app_row.get("application_name") or "(unnamed client)")
            item = app_counts.setdefault(app, {"application_name": app, "peak_sessions": 0, "peak_active_sessions": 0, "peak_lock_waiters": 0, "peak_idle_in_transaction": 0, "observed_samples": 0, "pids": set(), "lock_waits": 0, "max_query_age_seconds": 0})
            item["peak_sessions"] = max(item["peak_sessions"], int(app_row.get("total_sessions") or 0))
            item["peak_active_sessions"] = max(item["peak_active_sessions"], int(app_row.get("active_sessions") or 0))
            item["peak_lock_waiters"] = max(item["peak_lock_waiters"], int(app_row.get("lock_waiters") or 0))
            item["peak_idle_in_transaction"] = max(item["peak_idle_in_transaction"], int(app_row.get("idle_in_transaction") or 0))
            item["max_query_age_seconds"] = max(item["max_query_age_seconds"], int(app_row.get("max_query_age_seconds") or 0))
            item["observed_samples"] += 1
    for session in relevant_sessions:
        app = str(session.get("application_name") or "(unnamed client)")
        item = app_counts.setdefault(app, {"application_name": app, "peak_sessions": 0, "peak_active_sessions": 0, "peak_lock_waiters": 0, "peak_idle_in_transaction": 0, "observed_samples": 0, "pids": set(), "lock_waits": 0, "max_query_age_seconds": 0})
        if session.get("pid") is not None:
            item["pids"].add(int(session["pid"]))
        if session.get("blocking_pids"):
            item["lock_waits"] += 1
        item["max_query_age_seconds"] = max(item["max_query_age_seconds"], int(session.get("query_age_seconds") or 0))
    applications = [
        {**item, "pids": sorted(item["pids"])}
        for item in sorted(app_counts.values(), key=lambda row: (-row["peak_sessions"], row["application_name"]))
    ]

    host_samples = [
        (sample.get("host_metrics") or {})
        for sample in samples
        if sample.get("captured_at") in relevant_times and (sample.get("host_metrics") or {}).get("available")
    ]
    def metric_summary(key: str) -> dict[str, Any]:
        values = [float(item[key]) for item in host_samples if item.get(key) is not None]
        return {
            "observations": len(values),
            "average": round(sum(values) / len(values), 1) if values else None,
            "max": round(max(values), 1) if values else None,
        }

    signals = []
    cpu = metric_summary("cpu_percent")
    memory = metric_summary("memory_percent")
    disk = metric_summary("disk_percent")
    if cpu["max"] is not None and cpu["max"] >= 85:
        signals.append({"name": "Elevated collector-host CPU", "classification": "temporal_context_not_causation", "detail": f"Collector-host CPU reached {cpu['max']}% in {cpu['observations']} incident-triggering sample(s)."})
    if memory["max"] is not None and memory["max"] >= 90:
        signals.append({"name": "High collector-host memory utilization", "classification": "temporal_context_not_causation", "detail": f"Collector-host memory reached {memory['max']}% in {memory['observations']} incident-triggering sample(s)."})
    if disk["max"] is not None and disk["max"] >= 90:
        signals.append({"name": "High collector-host root disk utilization", "classification": "temporal_context_not_causation", "detail": f"Collector-host root disk utilization reached {disk['max']}% in {disk['observations']} incident-triggering sample(s)."})

    available = any((sample.get("host_metrics") or {}).get("available") for sample in samples)
    host = {
        "available": available,
        "scope": "collector_host_only",
        "cpu_percent": cpu,
        "memory_percent": memory,
        "disk_percent": disk,
        "note": "These metrics describe the machine running the Incident Intelligence collector. They are not PostgreSQL-server metrics unless both are confirmed to run on the same host.",
    }
    return {
        "observed_applications": applications,
        "host_context": host,
        "cross_layer_signals": signals,
        "application_context_note": "Application names and sessions are observed from pg_stat_activity during samples that triggered this rule. This does not establish affected end-user requests or business impact.",
    }


def build_incident_analysis(incident: dict[str, Any], samples: list[dict[str, Any]]) -> dict[str, Any]:
    periods = _sample_periods(incident, samples)
    timestamps = sorted(t for sample in samples if (t := _parse_time(sample.get("captured_at"))))
    intervals = [b.timestamp() - a.timestamp() for a, b in zip(timestamps, timestamps[1:]) if b > a]
    typical_interval = median(intervals) if intervals else None
    gaps = []
    if typical_interval:
        for left, right in zip(timestamps, timestamps[1:]):
            seconds = right.timestamp() - left.timestamp()
            if seconds > max(typical_interval * 2.5, typical_interval + 15):
                gaps.append({"from": left.isoformat(), "to": right.isoformat(), "gap_seconds": round(seconds)})

    coverage_notes: list[str] = []
    if not periods["before"]:
        coverage_notes.append("No pre-incident baseline sample is available in the retained window.")
    if not periods["after"]:
        coverage_notes.append("No post-incident sample is available in the retained window; recovery or rule clearance cannot be compared.")
    if not gaps and len(samples) < 2:
        coverage_notes.append("Too few samples exist to assess collection continuity.")
    if gaps:
        coverage_notes.append(f"{len(gaps)} collection gap(s) exceed the estimated sampling cadence and may hide short-lived events.")
    query_capture = any(bool((s.get("visibility") or {}).get("query_text_captured")) for s in samples)
    if not query_capture:
        coverage_notes.append("SQL text capture was disabled; query text was not retained by this product.")
    coverage_notes.append("Application traces, PostgreSQL server logs and verified database-host telemetry are not integrated; business impact and cross-layer causality remain unverified.")
    cross_layer = _cross_layer_context(incident, samples)
    coverage_notes.append("Collector-host metrics are contextual only and must not be interpreted as PostgreSQL-server metrics unless host identity is verified.")

    return {
        "observations": [
            f"The {incident.get('kind', 'unknown')} rule was observed {incident.get('observation_count', 0)} time(s).",
            f"The first and last sampled observations span {incident.get('first_seen')} to {incident.get('last_seen')}.",
            f"The incident is currently {incident.get('status')}; this status reflects rule detection, not independent business resolution.",
        ],
        "timeline": _timeline(incident, samples),
        "comparison": {
            "definition": "Before = samples earlier than first_seen; during = first_seen through last_seen; after = samples later than last_seen. Values are sampled snapshots, not continuous measurements.",
            "periods": {name: _summarize_period(items) for name, items in periods.items()},
        },
        "hypotheses": _hypotheses(incident, samples),
        "cross_layer_context": cross_layer,
        "coverage": {
            "sample_count": len(samples),
            "before_samples": len(periods["before"]),
            "during_samples": len(periods["during"]),
            "after_samples": len(periods["after"]),
            "estimated_interval_seconds": round(typical_interval, 1) if typical_interval else None,
            "collection_gaps": gaps,
            "notes": coverage_notes,
            "query_text_captured": query_capture,
        },
        "impact_assessment": {
            "status": "not_measured",
            "message": "Database-side observations are available, but affected requests, users, transactions or revenue cannot be quantified without application/business telemetry.",
        },
    }
