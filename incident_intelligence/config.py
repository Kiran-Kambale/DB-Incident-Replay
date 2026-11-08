from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    database_url: str
    collect_interval_seconds: int = 10
    long_query_seconds: int = 30
    idle_transaction_seconds: int = 60
    connection_warning_pct: float = 80.0
    connection_critical_pct: float = 95.0
    replication_lag_warning_bytes: int = 104_857_600
    capture_query_text: bool = False
    enable_pg_stat_statements: bool = False
    evidence_db_path: Path = Path("./data/incident_intelligence.sqlite3")


def load_settings() -> Settings:
    load_dotenv()
    return Settings(
        database_url=os.getenv("DATABASE_URL", "").strip(),
        collect_interval_seconds=max(5, int(os.getenv("COLLECT_INTERVAL_SECONDS", "10"))),
        long_query_seconds=max(1, int(os.getenv("LONG_QUERY_SECONDS", "30"))),
        idle_transaction_seconds=max(1, int(os.getenv("IDLE_TRANSACTION_SECONDS", "60"))),
        connection_warning_pct=float(os.getenv("CONNECTION_WARNING_PCT", "80")),
        connection_critical_pct=float(os.getenv("CONNECTION_CRITICAL_PCT", "95")),
        replication_lag_warning_bytes=max(1, int(os.getenv("REPLICATION_LAG_WARNING_BYTES", "104857600"))),
        capture_query_text=os.getenv("CAPTURE_QUERY_TEXT", "false").lower() in {"1", "true", "yes", "on"},
        enable_pg_stat_statements=os.getenv("ENABLE_PG_STAT_STATEMENTS", "false").lower() in {"1", "true", "yes", "on"},
        evidence_db_path=Path(os.getenv("EVIDENCE_DB_PATH", "./data/incident_intelligence.sqlite3")).expanduser(),
    )
