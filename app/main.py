from __future__ import annotations
import asyncio
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

app = FastAPI(title="DB Incident Replay - Local Lab", version="0.4.0")
HISTORY_DIR = ROOT / "data"
HISTORY_DB = HISTORY_DIR / "incident_history.sqlite3"


def init_history() -> None:
    """Create local-only storage for timestamped diagnostic snapshots."""
    HISTORY_DIR.mkdir(exist_ok=True)
    with sqlite3.connect(HISTORY_DB) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                captured_at TEXT NOT NULL,
                database_name TEXT NOT NULL,
                title TEXT NOT NULL,
                notes TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS monitor_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                captured_at TEXT NOT NULL,
                database_name TEXT NOT NULL,
                status TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS incident_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_key TEXT NOT NULL,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                severity TEXT NOT NULL,
                title TEXT NOT NULL,
                details_json TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_samples_captured ON monitor_samples(captured_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_started ON incident_events(started_at)")


init_history()
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


def connect():
    required = ["DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        raise RuntimeError("Missing .env settings: " + ", ".join(missing))
    return psycopg.connect(
        host=os.environ["DB_HOST"], port=int(os.environ["DB_PORT"]),
        dbname=os.environ["DB_NAME"], user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"], connect_timeout=3,
        options="-c statement_timeout=5000 -c default_transaction_read_only=on",
        row_factory=dict_row,
    )


def query(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    try:
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return list(cur.fetchall())
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database query failed: {exc}") from exc


MONITOR_INTERVAL_SECONDS = max(10, int(os.getenv("MONITOR_INTERVAL_SECONDS", "15")))
LONG_QUERY_SECONDS = max(1, int(os.getenv("LONG_QUERY_SECONDS", "30")))
IDLE_TXN_SECONDS = max(1, int(os.getenv("IDLE_TXN_SECONDS", "60")))
MONITOR_TASK: asyncio.Task | None = None
MONITOR_STATE: dict[str, Any] = {"running": False, "last_sample_at": None, "last_error": None, "interval_seconds": MONITOR_INTERVAL_SECONDS}


def collect_monitor_payload() -> dict[str, Any]:
    """Read-only sample. Query text is evidence and may contain sensitive literals."""
    h = query("SELECT current_database() AS database, now() AS checked_at, pg_postmaster_start_time() AS server_started_at")
    activity_sql = """
        SELECT pid, usename, application_name, client_addr, state,
               wait_event_type, wait_event,
               CASE WHEN query_start IS NOT NULL THEN now() - query_start END AS query_duration,
               CASE WHEN xact_start IS NOT NULL THEN now() - xact_start END AS transaction_age,
               query_start, xact_start, backend_start,
               left(query, 1500) AS query
        FROM pg_stat_activity
        WHERE datname = current_database() AND pid <> pg_backend_pid()
        ORDER BY query_start NULLS LAST LIMIT 250
    """
    acts = query(activity_sql)
    lock_data = locks()
    conn_data = connections()
    long_queries = query("""
        SELECT pid, usename, application_name, client_addr, state,
               now() - query_start AS query_duration, wait_event_type, wait_event,
               left(query, 1500) AS query
        FROM pg_stat_activity
        WHERE datname = current_database() AND pid <> pg_backend_pid()
          AND state = 'active' AND query_start < now() - (%s * interval '1 second')
        ORDER BY query_start ASC LIMIT 100
    """, (LONG_QUERY_SECONDS,))
    idle_txns = query("""
        SELECT pid, usename, application_name, client_addr, state,
               now() - xact_start AS transaction_age,
               now() - state_change AS state_age, wait_event_type, wait_event,
               left(query, 1500) AS query
        FROM pg_stat_activity
        WHERE datname = current_database() AND pid <> pg_backend_pid()
          AND state IN ('idle in transaction', 'idle in transaction (aborted)')
          AND xact_start < now() - (%s * interval '1 second')
        ORDER BY xact_start ASC LIMIT 100
    """, (IDLE_TXN_SECONDS,))
    db_stats = query("""
        SELECT datname, numbackends, xact_commit, xact_rollback, blks_read,
               blks_hit, round(100.0 * blks_hit / NULLIF(blks_hit + blks_read, 0), 2) AS cache_hit_pct,
               temp_files, pg_size_pretty(temp_bytes) AS temp_bytes_pretty,
               deadlocks, conflicts, stats_reset
        FROM pg_stat_database WHERE datname = current_database()
    """)
    findings = []
    if lock_data["count"]:
        findings.append({"key":"blocking", "severity":"critical", "title":f"{lock_data['count']} blocking relationship(s)", "count":lock_data["count"], "details":lock_data["items"][:10]})
    if long_queries:
        findings.append({"key":"long_queries", "severity":"warning", "title":f"{len(long_queries)} long-running active quer(ies)", "count":len(long_queries), "details":long_queries[:10]})
    if idle_txns:
        findings.append({"key":"idle_transactions", "severity":"warning", "title":f"{len(idle_txns)} long idle transaction(s)", "count":len(idle_txns), "details":idle_txns[:10]})
    util = conn_data.get("utilization_percent")
    if util is not None and util >= 80:
        findings.append({"key":"connections_high", "severity":"warning", "title":f"Connection utilization at {util}%", "count":util, "details":conn_data})
    return json_safe({"database":h[0]["database"], "checked_at":h[0]["checked_at"], "server_started_at":h[0]["server_started_at"],
        "activity":{"count":len(acts),"items":acts}, "locks":lock_data, "connections":conn_data,
        "long_queries":{"threshold_seconds":LONG_QUERY_SECONDS,"count":len(long_queries),"items":long_queries},
        "idle_transactions":{"threshold_seconds":IDLE_TXN_SECONDS,"count":len(idle_txns),"items":idle_txns},
        "database_stats":db_stats[0] if db_stats else {}, "findings":findings,
        "failed_query_note":"Failed statements are not reliably available from pg_stat_activity after they finish. PostgreSQL error logging must be configured separately to retain failed SQL evidence."})


def persist_monitor_sample(payload: dict[str, Any]) -> None:
    captured_at = str(payload["checked_at"])
    database_name = str(payload["database"])
    status = "alert" if payload.get("findings") else "ok"
    active_keys = {f["key"]: f for f in payload.get("findings", [])}
    with sqlite3.connect(HISTORY_DB) as conn:
        conn.execute("INSERT INTO monitor_samples(captured_at,database_name,status,payload_json) VALUES(?,?,?,?)",
                     (captured_at, database_name, status, json.dumps(payload)))
        # Create an event when a condition first appears; close it when it clears.
        existing = conn.execute("SELECT event_key FROM incident_events WHERE active=1").fetchall()
        existing_keys = {row[0] for row in existing}
        for key, finding in active_keys.items():
            if key not in existing_keys:
                conn.execute("INSERT INTO incident_events(event_key,started_at,severity,title,details_json,active) VALUES(?,?,?,?,?,1)",
                    (key, captured_at, finding["severity"], finding["title"], json.dumps(finding)))
            else:
                conn.execute("UPDATE incident_events SET title=?, severity=?, details_json=? WHERE event_key=? AND active=1",
                    (finding["title"], finding["severity"], json.dumps(finding), key))
        for key in existing_keys - set(active_keys):
            conn.execute("UPDATE incident_events SET active=0, ended_at=? WHERE event_key=? AND active=1", (captured_at, key))
        # Seven-day local retention for high-frequency samples; events and manual snapshots remain.
        conn.execute("DELETE FROM monitor_samples WHERE julianday(captured_at) < julianday('now','-7 days')")


async def monitor_loop() -> None:
    MONITOR_STATE["running"] = True
    while True:
        try:
            payload = await asyncio.to_thread(collect_monitor_payload)
            await asyncio.to_thread(persist_monitor_sample, payload)
            MONITOR_STATE["last_sample_at"] = str(payload["checked_at"])
            MONITOR_STATE["last_error"] = None
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            MONITOR_STATE["last_error"] = str(exc)[:500]
        await asyncio.sleep(MONITOR_INTERVAL_SECONDS)


@app.on_event("startup")
async def start_monitor() -> None:
    global MONITOR_TASK
    if os.getenv("AUTO_MONITOR", "true").lower() in ("1", "true", "yes", "on"):
        MONITOR_TASK = asyncio.create_task(monitor_loop())


@app.on_event("shutdown")
async def stop_monitor() -> None:
    global MONITOR_TASK
    if MONITOR_TASK:
        MONITOR_TASK.cancel()
        try:
            await MONITOR_TASK
        except asyncio.CancelledError:
            pass
        MONITOR_TASK = None
    MONITOR_STATE["running"] = False


@app.get("/api/monitor/status")
def monitor_status():
    return {**MONITOR_STATE, "auto_monitor_enabled": os.getenv("AUTO_MONITOR", "true").lower() in ("1", "true", "yes", "on"),
            "long_query_seconds": LONG_QUERY_SECONDS, "idle_transaction_seconds": IDLE_TXN_SECONDS,
            "retention_days": 7, "note": "Polling samples are local observations, not a complete audit trail. Failed statements require PostgreSQL server logging."}


@app.get("/api/monitor/latest")
def monitor_latest():
    with sqlite3.connect(HISTORY_DB) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT id,captured_at,database_name,status,payload_json FROM monitor_samples ORDER BY id DESC LIMIT 1").fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="No automatic samples yet. Check database connectivity and monitor status.")
    result = dict(row); result["payload"] = json.loads(result.pop("payload_json")); return result


@app.get("/api/monitor/history")
def monitor_history(limit: int = 100):
    limit = min(max(limit, 1), 500)
    with sqlite3.connect(HISTORY_DB) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT id,captured_at,database_name,status,payload_json FROM monitor_samples ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    items=[]
    for row in rows:
        item=dict(row)
        try:
            payload=json.loads(item.pop("payload_json"))
            item["sessions"]=payload.get("connections",{}).get("total_sessions",0)
            item["blocking_count"]=payload.get("locks",{}).get("count",0)
            item["long_query_count"]=payload.get("long_queries",{}).get("count",0)
        except Exception:
            item["sessions"]=0; item["blocking_count"]=0; item["long_query_count"]=0
        items.append(item)
    return {"count":len(items), "items":items}


@app.get("/api/events")
def incident_events(limit: int = 100):
    limit = min(max(limit, 1), 500)
    with sqlite3.connect(HISTORY_DB) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT id,event_key,started_at,ended_at,severity,title,details_json,active FROM incident_events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    items=[]
    for row in rows:
        item=dict(row); item["details"]=json.loads(item.pop("details_json")); items.append(item)
    return {"count":len(items),"items":items}


@app.get("/api/diagnostics/long-queries")
def diagnostics_long_queries():
    rows = query("""
        SELECT pid, usename, application_name, client_addr, state,
               now() - query_start AS query_duration, wait_event_type, wait_event,
               left(query, 1500) AS query
        FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid()
          AND state='active' AND query_start < now() - (%s * interval '1 second')
        ORDER BY query_start ASC LIMIT 100
    """, (LONG_QUERY_SECONDS,))
    return {"threshold_seconds":LONG_QUERY_SECONDS,"count":len(rows),"items":rows}


@app.get("/api/diagnostics/idle-transactions")
def diagnostics_idle_transactions():
    rows = query("""
        SELECT pid, usename, application_name, client_addr, state,
               now()-xact_start AS transaction_age, now()-state_change AS state_age,
               wait_event_type, wait_event, left(query,1500) AS query
        FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid()
          AND state IN ('idle in transaction','idle in transaction (aborted)')
        ORDER BY xact_start NULLS LAST LIMIT 100
    """)
    return {"threshold_seconds": IDLE_TXN_SECONDS, "count":len(rows),"items":rows}


@app.get("/")
def home():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/health")
def health():
    rows = query("SELECT version() AS version, current_database() AS database, now() AS checked_at")
    return rows[0]


@app.get("/api/diagnostics/locks")
def locks():
    sql = """
    SELECT blocked.pid AS blocked_pid,
           blocked.usename AS blocked_user,
           blocked.application_name AS blocked_application,
           now() - blocked.query_start AS blocked_duration,
           blocked.wait_event_type,
           blocked.wait_event,
           left(blocked.query, 500) AS blocked_query,
           blocker.pid AS blocker_pid,
           blocker.usename AS blocker_user,
           now() - blocker.xact_start AS blocker_transaction_age,
           left(blocker.query, 500) AS blocker_query,
           blocker.state AS blocker_state
    FROM pg_stat_activity blocked
    CROSS JOIN LATERAL unnest(pg_blocking_pids(blocked.pid)) AS bp(pid)
    JOIN pg_stat_activity blocker ON blocker.pid = bp.pid
    WHERE blocked.datname = current_database()
    ORDER BY blocked.query_start NULLS LAST
    """
    rows = query(sql)
    return {"count": len(rows), "items": rows,
            "interpretation": "Rows show observed blocking relationships at the time of this check. Verify transaction context before terminating sessions."}


@app.get("/api/diagnostics/activity")
def activity():
    sql = """
    SELECT pid, usename, application_name, client_addr, state,
           wait_event_type, wait_event,
           CASE WHEN query_start IS NOT NULL THEN now() - query_start END AS query_duration,
           CASE WHEN xact_start IS NOT NULL THEN now() - xact_start END AS transaction_age,
           left(query, 500) AS query
    FROM pg_stat_activity
    WHERE datname = current_database() AND pid <> pg_backend_pid()
    ORDER BY query_start NULLS LAST
    LIMIT 100
    """
    rows = query(sql)
    return {"count": len(rows), "items": rows}


@app.get("/api/diagnostics/connections")
def connections():
    sql = """
    SELECT state, count(*)::int AS sessions
    FROM pg_stat_activity
    WHERE datname = current_database()
    GROUP BY state ORDER BY sessions DESC
    """
    rows = query(sql)
    total = sum(r["sessions"] for r in rows)
    max_rows = query("SELECT setting::int AS max_connections FROM pg_settings WHERE name = 'max_connections'")
    maximum = max_rows[0]["max_connections"] if max_rows else None
    return {"total_sessions": total, "max_connections": maximum,
            "utilization_percent": round(total / maximum * 100, 1) if maximum else None,
            "by_state": rows,
            "interpretation": "Counts are scoped to the current database here. Compare server-wide usage before diagnosing global connection exhaustion."}


@app.get("/api/diagnostics/summary")
def summary():
    try:
        h = health()
        l = locks()
        c = connections()
        a = activity()
        findings = []
        if l["count"]:
            findings.append({
                "severity": "warning",
                "title": f"{l['count']} blocking relationship(s) detected",
                "evidence": "Observed live PostgreSQL blocking relationships at this check. A blocker PID identifies a session involved in the wait; it does not by itself prove the underlying application root cause.",
                "next": "Start with the oldest blocker transaction. Check the blocker state and query, identify the owning application/request, and confirm impact with the application owner. Do not terminate a session automatically."
            })
            for item in l["items"][:5]:
                wait = item.get("wait_event_type") or "unknown wait type"
                blocker_state = item.get("blocker_state") or "unknown state"
                txn_age = item.get("blocker_transaction_age") or "unknown transaction age"
                likely = ("The blocker is idle in a transaction; it may have left a transaction open without committing or rolling back. Verify with the application owner before remediation."
                          if blocker_state == "idle in transaction" else
                          "The blocker is holding a lock needed by the blocked session. Inspect its current/last query and transaction context to determine why it has not released the lock.")
                findings.append({
                    "severity": "warning",
                    "title": f"Blocked PID {item.get('blocked_pid')} is waiting on blocker PID {item.get('blocker_pid')}",
                    "evidence": f"Wait type: {wait}. Blocker state: {blocker_state}. Blocker transaction age: {txn_age}. Blocked SQL: {item.get('blocked_query') or 'not visible'}",
                    "next": likely
                })
        else:
            findings.append({"severity": "ok", "title": "No blocking relationship detected right now", "next": "This is a point-in-time check; a past lock incident requires historical logs or prior samples."})
        if c.get("utilization_percent") is not None and c["utilization_percent"] >= 80:
            findings.append({"severity": "warning", "title": f"Connection count is {c['utilization_percent']}% of max_connections (current database count)", "next": "Check server-wide connection usage, pool settings, idle sessions and connection trends."})
        else:
            findings.append({"severity": "info", "title": "No high connection threshold detected by this simple rule", "next": "Check all databases and historical peaks before ruling out connection pressure."})
        long_xacts = [r for r in a["items"] if r.get("transaction_age") and str(r["transaction_age"]) not in ("0:00:00",)]
        if long_xacts:
            findings.append({"severity": "info", "title": f"{len(long_xacts)} session(s) have an open transaction", "next": "Review transaction age and state; an open transaction is not automatically a problem."})
        return {"database": h["database"], "checked_at": h["checked_at"], "findings": findings,
                "locks": l["count"], "sessions": c["total_sessions"], "activity_rows": a["count"],
                "note": "Heuristic findings only. No session is terminated and no database data is modified."}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


class CaptureRequest(BaseModel):
    title: str = Field(default="", max_length=120)
    notes: str = Field(default="", max_length=1000)


def json_safe(value: Any) -> Any:
    """Convert PostgreSQL date/time and interval values to JSON-safe strings."""
    return json.loads(json.dumps(value, default=str))


@app.post("/api/history/capture")
def capture_snapshot(request: CaptureRequest):
    """Collect a point-in-time diagnostic snapshot and persist it locally."""
    try:
        h = health()
        s = summary()
        l = locks()
        a = activity()
        c = connections()
        try:
            monitor_evidence = collect_monitor_payload()
        except Exception as monitor_exc:
            monitor_evidence = {"collection_error": str(monitor_exc)[:500]}
        captured_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        title = request.title.strip() or f"Snapshot {captured_at.replace('T', ' ')}"
        payload = json_safe({
            "captured_at": captured_at,
            "database": h["database"],
            "summary": s,
            "locks": l,
            "activity": a,
            "connections": c,
            "monitor_evidence": monitor_evidence,
            "limitations": "Snapshot includes point-in-time evidence only. Automatic polling can preserve sampled states but can miss events shorter than the interval. Failed statements require PostgreSQL server error logging. Query text may contain sensitive values; keep this local database private and review/redact before sharing."
        })
        with sqlite3.connect(HISTORY_DB) as conn:
            cur = conn.execute(
                "INSERT INTO snapshots (captured_at, database_name, title, notes, payload_json) VALUES (?, ?, ?, ?, ?)",
                (captured_at, h["database"], title, request.notes.strip(), json.dumps(payload))
            )
            snapshot_id = cur.lastrowid
        return {"id": snapshot_id, "captured_at": captured_at, "database": h["database"], "title": title,
                "message": "Snapshot saved to local incident history.", "note": payload["limitations"]}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Could not capture snapshot: {exc}") from exc


@app.get("/api/history")
def list_history():
    """Return saved snapshot metadata, newest first."""
    with sqlite3.connect(HISTORY_DB) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, captured_at, database_name, title, notes FROM snapshots ORDER BY id DESC LIMIT 100"
        ).fetchall()
    return {"count": len(rows), "items": [dict(row) for row in rows]}


@app.get("/api/history/{snapshot_id}")
def get_snapshot(snapshot_id: int):
    """Return one saved snapshot, including its evidence payload."""
    with sqlite3.connect(HISTORY_DB) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT id, captured_at, database_name, title, notes, payload_json FROM snapshots WHERE id = ?",
            (snapshot_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    result = dict(row)
    result["payload"] = json.loads(result.pop("payload_json"))
    return result
