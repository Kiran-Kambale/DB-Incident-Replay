from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from typing import Any


class CollectorState:
    def __init__(self) -> None:
        self._lock = Lock()
        self._data: dict[str, Any] = {
            "connected": False,
            "last_attempt_at": None,
            "last_success_at": None,
            "last_error": None,
            "database": None,
            "server_version": None,
            "collector_pid": None,
        }

    def update(self, **values: Any) -> None:
        with self._lock:
            self._data.update(values)

    def attempted(self) -> None:
        self.update(last_attempt_at=datetime.now(timezone.utc).isoformat())

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._data)


collector_state = CollectorState()
