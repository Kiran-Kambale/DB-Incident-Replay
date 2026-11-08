from __future__ import annotations

from typing import Any


def _human_bytes(value: int | None) -> str:
    if value is None:
        return "Not available"
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def build_incident_report(incident: dict[str, Any], samples: list[dict[str, Any]], capture_query_text: bool, analysis: dict[str, Any] | None = None) -> str:
    details = incident.get("details") or {}
    kind = incident.get("kind")
    lines = [
        f"# PostgreSQL Incident Intelligence — {incident['title']}",
        "",
        f"- Incident ID: `{incident['id']}`",
        f"- Database: `{incident['db_name']}`",
        f"- Severity: **{incident['severity'].upper()}**",
        f"- Status: **{incident['status']}**",
        f"- First observed: {incident['first_seen']}",
        f"- Last observed: {incident['last_seen']}",
        f"- Observations while active: {incident['observation_count']}",
        "",
        "## Summary",
        incident["summary"],
        "",
        "## What was observed",
    ]

    if kind == "connection_pressure":
        lines += [
            f"- Visible client backends: {details.get('used_connections', 'unknown')}",
            f"- max_connections: {details.get('max_connections', 'unknown')}",
            f"- Estimated slot utilization: {details.get('utilization_pct', 'unknown')}%",
            "- This is a sampled connection-slot ratio. It does not prove that connection attempts failed or account for every reserved-slot nuance.",
        ]
    elif kind == "lock_wait":
        lines.append(f"- Blocked sessions observed: {details.get('blocked_session_count', 0)}")
        for session in details.get("sessions", [])[:10]:
            lines.append(f"- PID {session.get('pid')}: state={session.get('state')}, wait={session.get('wait_event_type')}/{session.get('wait_event')}, blockers={session.get('blocking_pids')}, app={session.get('application_name') or 'unknown'}")
            if session.get("query_text"):
                sql_text = str(session["query_text"]).replace("`", "'")[:500]
                lines.append(f"  - Captured SQL text: `{sql_text}`")
    elif kind == "long_query":
        lines.append(f"- Configured duration threshold: {details.get('threshold_seconds')} seconds")
        for session in details.get("sessions", [])[:10]:
            lines.append(f"- PID {session.get('pid')}: age={session.get('query_age_seconds')}s, app={session.get('application_name') or 'unknown'}, user={session.get('usename') or 'unknown'}")
            if session.get("query_text"):
                sql_text = str(session["query_text"]).replace("`", "'")[:500]
                lines.append(f"  - Captured SQL text: `{sql_text}`")
    elif kind == "idle_in_transaction":
        lines.append(f"- Configured transaction-age threshold: {details.get('threshold_seconds')} seconds")
        for session in details.get("sessions", [])[:10]:
            lines.append(f"- PID {session.get('pid')}: transaction age={session.get('xact_age_seconds')}s, state={session.get('state')}, app={session.get('application_name') or 'unknown'}")
    elif kind == "replication_lag":
        lines += [
            f"- Streaming replicas: {details.get('replica_count')}",
            f"- Maximum sampled replay distance: {_human_bytes(details.get('max_replica_lag_bytes'))}",
            f"- Configured threshold: {_human_bytes(details.get('threshold_bytes'))}",
            "- This is an LSN byte-distance observation, not a time-based lag measurement.",
        ]
    elif kind == "deadlock_increase":
        lines += [
            f"- Deadlock counter increase between successful samples: {details.get('deadlock_delta')}",
            f"- Counter total at the later sample: {details.get('counter_total')}",
            "- The cumulative counter does not identify the transactions or SQL statements involved.",
        ]

    lines += ["", "## Evidence coverage", f"- Historical snapshots available in this report window: {len(samples)}"]
    if samples:
        lines.append(f"- Earliest retained sample in window: {samples[0]['captured_at']}")
        lines.append(f"- Latest retained sample in window: {samples[-1]['captured_at']}")
        versions = sorted({s.get("server_version") or "unknown" for s in samples})
        lines.append(f"- PostgreSQL version(s) observed: {', '.join(versions)}")
        for sample in samples[-12:]:
            lines.append(
                f"- {sample['captured_at']}: active={sample.get('active_sessions')}, "
                f"connections={sample.get('total_client_backends')}/{sample.get('max_connections')}, "
                f"lock_waiters={sample.get('lock_waiters')}, idle-in-tx={sample.get('idle_in_transaction')}"
            )
        matched = []
        for sample in samples:
            for finding in sample.get("detections", []):
                if finding.get("kind") == kind:
                    matched.append((sample["captured_at"], finding.get("details", {})))
        if matched:
            lines += ["", "### Samples that triggered this rule"]
            for captured_at, sample_details in matched[-15:]:
                sample_sessions = sample_details.get("sessions", [])
                pids = ", ".join(str(x.get("pid")) for x in sample_sessions[:8] if x.get("pid")) or "not recorded"
                lines.append(f"- {captured_at}: session PIDs={pids}; details={sample_details}")
        first_stats, last_stats = samples[0].get("stats", {}), samples[-1].get("stats", {})
        if first_stats.get("stats_reset") == last_stats.get("stats_reset") and first_stats.get("stats_reset") is not None:
            lines += ["", "### Database counter deltas across retained samples"]
            for key, label in (("xact_commit", "Committed transactions"), ("xact_rollback", "Rolled-back transactions"),
                               ("deadlocks", "Deadlocks"), ("temp_bytes", "Temporary bytes written")):
                try:
                    delta = int(last_stats.get(key, 0)) - int(first_stats.get(key, 0))
                    lines.append(f"- {label}: {delta:,}")
                except (TypeError, ValueError):
                    pass
            try:
                hit_delta = int(last_stats.get("blks_hit", 0)) - int(first_stats.get("blks_hit", 0))
                read_delta = int(last_stats.get("blks_read", 0)) - int(first_stats.get("blks_read", 0))
                if hit_delta >= 0 and read_delta >= 0 and hit_delta + read_delta:
                    lines.append(f"- Shared buffer cache hit ratio across observed counter delta: {hit_delta / (hit_delta + read_delta) * 100:.2f}%")
            except (TypeError, ValueError):
                pass
            lines.append("- These are database-wide cumulative counter differences between the first and last retained samples, not per-query measurements.")
    else:
        lines.append("- No samples were available for the selected time window.")

    visibility = samples[-1].get("visibility", {}) if samples else {}
    if visibility and not visibility.get("has_pg_read_all_stats"):
        lines.append("- Visibility warning: the connected role is not a member of pg_read_all_stats. Session details for other users may be restricted.")
    if not capture_query_text:
        lines.append("- SQL text capture is disabled. Query text was intentionally not persisted by this product.")
    else:
        lines.append("- SQL text capture is enabled. Review captured statements for sensitive literals, personal data or secrets before sharing this report.")
    lines.append("- Sampling can miss events shorter than the collection interval. Missing observations are not proof that an event did not occur.")

    if not analysis:
        lines += ["", "## Investigation hypotheses (not confirmed root causes)"]
        hypothesis_map = {
            "connection_pressure": "Connection-slot pressure may have contributed to connection delays. Verify application pool queues, connection errors, reserved slots and connection acquisition timeouts.",
            "lock_wait": "Lock contention was observed during sampled periods. Determine the blocking transaction, lock mode, transaction age and affected application requests before attributing impact.",
            "long_query": "Long-running active statements were observed. Compare their expected runtime, query plan, wait events, resource consumption and application timeout behaviour.",
            "idle_in_transaction": "Open idle transactions were observed. Assess retained locks, vacuum impact, transaction ownership and whether application code left transactions open.",
            "replication_lag": "Replica replay distance exceeded the configured threshold. Check WAL generation rate, network throughput, replica I/O, replay conflicts and standby workload.",
            "deadlock_increase": "The deadlock counter increased. Correlate PostgreSQL logs and application traces to identify transaction ordering and statements involved.",
        }
        lines.append(f"- {hypothesis_map.get(kind, 'Further investigation is required. No cause has been confirmed.')}")
        lines += ["", "## Recommended next checks", "1. Compare this report window with application logs, traces and deployment events.", "2. Inspect the original PostgreSQL logs for the same timestamps, especially lock, deadlock, timeout and connection errors.", "3. Verify the suspected mechanism with a controlled reproduction or query-level evidence.", "4. Record the verified cause and remediation separately; do not treat this generated report as proof of causation."]
    if analysis:
        lines += ["", "## Incident timeline"]
        for event in analysis.get("timeline", []):
            lines.append(f"- **{event.get('timestamp')} — {event.get('title')}**: {event.get('description')}")
        if not analysis.get("timeline"):
            lines.append("- No timeline events could be reconstructed from retained samples.")

        lines += ["", "## Before / during / after comparison"]
        lines.append(analysis.get("comparison", {}).get("definition", "Values are sampled snapshots."))
        periods = analysis.get("comparison", {}).get("periods", {})
        for period_name in ("before", "during", "after"):
            period = periods.get(period_name, {})
            lines += ["", f"### {period_name.title()} ({period.get('sample_count', 0)} samples)"]
            for key, metric in period.get("metrics", {}).items():
                if metric.get("observations"):
                    lines.append(
                        f"- {metric.get('label')}: min={metric.get('min')}, "
                        f"average={metric.get('average')}, max={metric.get('max')}, last={metric.get('last')}"
                    )
                else:
                    lines.append(f"- {metric.get('label')}: not available in this period")

        cross_layer = analysis.get("cross_layer_context", {})
        lines += ["", "## Cross-layer context"]
        host = cross_layer.get("host_context", {})
        lines.append("- Host metric scope: collector host only; these are not PostgreSQL-server metrics unless host identity is verified.")
        for metric_name, label in (("cpu_percent", "Collector-host CPU"), ("memory_percent", "Collector-host memory"), ("disk_percent", "Collector-host root disk")):
            metric = host.get(metric_name, {})
            lines.append(f"- {label}: average={metric.get('average')}, max={metric.get('max')}, observations={metric.get('observations', 0)}")
        if cross_layer.get("cross_layer_signals"):
            lines.append("- Temporal context signals (not proof of causation):")
            lines.extend([f"  - {signal.get('name')}: {signal.get('detail')}" for signal in cross_layer.get("cross_layer_signals", [])])
        else:
            lines.append("- No configured elevated collector-host resource signal was observed in rule-triggering samples, or host metrics were unavailable.")
        lines.append("- Application workloads observed in samples that triggered this rule:")
        for app in cross_layer.get("observed_applications", []):
            lines.append(f"  - {app.get('application_name')}: peak sessions={app.get('peak_sessions')}, peak active={app.get('peak_active_sessions')}, peak lock waiters={app.get('peak_lock_waiters')}, PIDs={', '.join(map(str, app.get('pids', []))) or 'not retained'}")
        if not cross_layer.get("observed_applications"):
            lines.append("  - No application-name breakdown was retained for the triggering samples.")
        lines.append(f"- {cross_layer.get('application_context_note', 'Application metadata is contextual and does not quantify end-user impact.')}")

        lines += ["", "## Evidence-backed investigation hypotheses"]
        for hypothesis in analysis.get("hypotheses", []):
            lines += ["", f"### {hypothesis.get('title')}", f"- Classification: **{hypothesis.get('classification', 'hypothesis')}**", f"- Confidence: **{hypothesis.get('confidence', 'low')}** (not a confirmed cause)"]
            lines.append("- Supporting evidence:")
            lines.extend([f"  - {item}" for item in hypothesis.get("supporting_evidence", [])] or ["  - No supporting detail retained."])
            lines.append("- Missing or alternative evidence:")
            lines.extend([f"  - {item}" for item in hypothesis.get("missing_or_alternative_evidence", [])] or ["  - None listed."])
            lines.append("- Next checks:")
            lines.extend([f"  - {item}" for item in hypothesis.get("next_checks", [])] or ["  - Review source evidence manually."])

        coverage = analysis.get("coverage", {})
        lines += ["", "## Evidence coverage and limitations"]
        lines.append(f"- Samples: before={coverage.get('before_samples', 0)}, during={coverage.get('during_samples', 0)}, after={coverage.get('after_samples', 0)}.")
        lines.append(f"- Estimated collection interval: {coverage.get('estimated_interval_seconds') or 'not enough data'} seconds.")
        for note in coverage.get("notes", []):
            lines.append(f"- {note}")
        for gap in coverage.get("collection_gaps", []):
            lines.append(f"- Collection gap: {gap.get('gap_seconds')} seconds from {gap.get('from')} to {gap.get('to')}.")

        impact = analysis.get("impact_assessment", {})
        lines += ["", "## Business impact assessment", f"- Status: **{impact.get('status', 'not_measured')}**", f"- {impact.get('message', 'Business impact was not measured.')}" ]

    lines += ["", "---", "Generated locally by PostgreSQL Incident Intelligence. This report contains sampled evidence and deterministic investigation hypotheses. It does not confirm root cause or quantify business impact without additional telemetry and human verification.", ""]
    return "\n".join(lines)
