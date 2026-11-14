from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from .collector import PostgresCollector
from .config import load_settings
from .investigation import build_incident_analysis
from .reports import build_incident_report
from .state import collector_state
from .store import EvidenceStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("pg_incident_intelligence")

BASE_DIR = Path(__file__).resolve().parent
settings = load_settings()
store = EvidenceStore(settings.evidence_db_path)
collector = PostgresCollector(settings, store)


async def collector_loop() -> None:
    while True:
        try:
            result = await asyncio.to_thread(collector.collect_once)
            logger.info("Captured PostgreSQL evidence for database=%s findings=%s", result["db_name"], len(result["detections"]))
        except Exception as exc:
            # Keep the web UI available so users can diagnose connection/permission problems.
            logger.warning("Evidence collection failed: %s: %s", type(exc).__name__, exc)
        await asyncio.sleep(settings.collect_interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(collector_loop(), name="postgresql-evidence-collector")
    yield
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


app = FastAPI(
    title="PostgreSQL Incident Intelligence",
    version="0.3.0",
    description="Local, read-only PostgreSQL evidence collection and incident reconstruction MVP.",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.get("/", include_in_schema=False)
async def dashboard() -> FileResponse:
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "product": "PostgreSQL Incident Intelligence", "version": "0.3.0"}


@app.get("/api/overview")
async def overview() -> dict[str, Any]:
    latest = store.latest_sample()
    samples = store.recent_samples(90)
    trend = [
        {
            "captured_at": s["captured_at"],
            "total_client_backends": s["total_client_backends"],
            "active_sessions": s["active_sessions"],
            "lock_waiters": s["lock_waiters"],
            "idle_in_transaction": s["idle_in_transaction"],
            "connection_pct": round((s["total_client_backends"] / s["max_connections"] * 100), 1) if s.get("max_connections") else 0,
            "host_cpu_percent": (s.get("host_metrics") or {}).get("cpu_percent"),
            "host_memory_percent": (s.get("host_metrics") or {}).get("memory_percent"),
        }
        for s in samples
    ]
    return {
        "collector": collector_state.snapshot(),
        "settings": {
            "collect_interval_seconds": settings.collect_interval_seconds,
            "long_query_seconds": settings.long_query_seconds,
            "idle_transaction_seconds": settings.idle_transaction_seconds,
            "capture_query_text": settings.capture_query_text,
        },
        "latest": latest,
        "trend": trend,
        "incidents": store.list_incidents("open", 20),
        "counts": store.counts(),
    }


@app.get("/api/analytics")
async def analytics() -> dict[str, Any]:
    samples = store.recent_samples(120)
    latest = samples[-1] if samples else None
    host_trend = [
        {
            "captured_at": sample.get("captured_at"),
            "cpu_percent": (sample.get("host_metrics") or {}).get("cpu_percent"),
            "memory_percent": (sample.get("host_metrics") or {}).get("memory_percent"),
            "disk_percent": (sample.get("host_metrics") or {}).get("disk_percent"),
            "disk_read_bytes_per_sec": (sample.get("host_metrics") or {}).get("disk_read_bytes_per_sec"),
            "disk_write_bytes_per_sec": (sample.get("host_metrics") or {}).get("disk_write_bytes_per_sec"),
        }
        for sample in samples
    ]
    return {
        "host_latest": (latest or {}).get("host_metrics", {}),
        "host_trend": host_trend,
        "applications": (latest or {}).get("application_summary", []),
        "incident_patterns_7d": store.incident_patterns(days=7, limit=8),
        "scope_note": "Host metrics describe the machine running this collector. They are not PostgreSQL server metrics unless the collector and PostgreSQL server are confirmed to run on the same host.",
    }


@app.get("/api/incidents")
async def incidents(status: str = Query("all", pattern="^(all|open|resolved)$"), limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
    return {"items": store.list_incidents(status, limit)}


@app.get("/api/incidents/{incident_id}")
async def incident_detail(incident_id: str) -> dict[str, Any]:
    item = store.get_incident(incident_id)
    if not item:
        raise HTTPException(status_code=404, detail="Incident not found")
    samples = store.samples_for_incident(item["first_seen"], item["last_seen"], padding_seconds=settings.collect_interval_seconds * 3, closed_at=item.get("closed_at"))
    analysis = build_incident_analysis(item, samples)
    return {"incident": item, "samples": samples, "analysis": analysis}


@app.get("/api/incidents/{incident_id}/report.md")
async def incident_report(incident_id: str) -> PlainTextResponse:
    item = store.get_incident(incident_id)
    if not item:
        raise HTTPException(status_code=404, detail="Incident not found")
    samples = store.samples_for_incident(item["first_seen"], item["last_seen"], padding_seconds=settings.collect_interval_seconds * 3, closed_at=item.get("closed_at"))
    analysis = build_incident_analysis(item, samples)
    report = build_incident_report(item, samples, settings.capture_query_text, analysis)
    return PlainTextResponse(
        report,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="incident-{incident_id[:8]}-rca.md"'},
    )


@app.get("/api/evidence")
async def evidence(limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
    return {"items": store.recent_samples(limit)}


@app.post("/api/collect")
async def collect_now() -> dict[str, Any]:
    try:
        result = await asyncio.to_thread(collector.collect_once)
        return {"ok": True, **result}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Collection failed: {type(exc).__name__}: {exc}") from exc


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("incident_intelligence.main:app", host="0.0.0.0", port=8000, reload=False)
