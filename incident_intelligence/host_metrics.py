from __future__ import annotations

import os
import platform
import socket
import time
from typing import Any


class HostMetricsSampler:
    """Collect lightweight metrics from the machine running this collector.

    These are deliberately labelled collector-host metrics. They are not
    represented as PostgreSQL-server metrics when PostgreSQL is remote.
    """

    def __init__(self) -> None:
        self._previous_io: tuple[int, int] | None = None
        self._previous_monotonic: float | None = None
        self._cpu_warmed_up = False

    def collect(self) -> dict[str, Any]:
        try:
            import psutil
        except ImportError:
            return {
                "available": False,
                "scope": "collector_host_only",
                "error": "psutil is not installed; install requirements to enable collector-host metrics.",
            }

        now = time.monotonic()
        cpu = psutil.cpu_percent(interval=None)
        if not self._cpu_warmed_up:
            # The first non-blocking cpu_percent() result is not meaningful.
            cpu_value: float | None = None
            self._cpu_warmed_up = True
        else:
            cpu_value = round(float(cpu), 1)

        memory = psutil.virtual_memory()
        root_path = os.path.abspath(os.sep)
        try:
            disk = psutil.disk_usage(root_path)
            disk_data = {
                "disk_percent": round(float(disk.percent), 1),
                "disk_used_bytes": int(disk.used),
                "disk_total_bytes": int(disk.total),
                "disk_path": root_path,
            }
        except (OSError, PermissionError):
            disk_data = {
                "disk_percent": None,
                "disk_used_bytes": None,
                "disk_total_bytes": None,
                "disk_path": root_path,
            }

        read_rate: float | None = None
        write_rate: float | None = None
        try:
            io = psutil.disk_io_counters(perdisk=False)
        except (psutil.Error, OSError):
            io = None
        if io is not None:
            current = (int(io.read_bytes), int(io.write_bytes))
            if self._previous_io is not None and self._previous_monotonic is not None:
                elapsed = now - self._previous_monotonic
                if elapsed > 0:
                    read_rate = round(max(0, current[0] - self._previous_io[0]) / elapsed, 1)
                    write_rate = round(max(0, current[1] - self._previous_io[1]) / elapsed, 1)
            self._previous_io = current
            self._previous_monotonic = now

        try:
            process = psutil.Process()
            process_rss = int(process.memory_info().rss)
        except (psutil.Error, OSError):
            process_rss = None

        return {
            "available": True,
            "scope": "collector_host_only",
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
            "cpu_percent": cpu_value,
            "memory_percent": round(float(memory.percent), 1),
            "memory_used_bytes": int(memory.used),
            "memory_total_bytes": int(memory.total),
            **disk_data,
            "disk_read_bytes_per_sec": read_rate,
            "disk_write_bytes_per_sec": write_rate,
            "collector_process_rss_bytes": process_rss,
        }
