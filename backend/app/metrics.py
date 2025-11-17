from __future__ import annotations

from importlib import import_module
from typing import Iterable, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - used only by type checkers
    from prometheus_client import CONTENT_TYPE_LATEST as _CONTENT_TYPE
    from prometheus_client import Counter, Gauge, CollectorRegistry, generate_latest as _generate_latest
else:  # Lazy import so IDEs without the dependency stop flagging the module
    _prometheus = import_module("prometheus_client")
    _CONTENT_TYPE = getattr(_prometheus, "CONTENT_TYPE_LATEST", "text/plain")
    CollectorRegistry = getattr(_prometheus, "CollectorRegistry")
    Counter = getattr(_prometheus, "Counter")
    Gauge = getattr(_prometheus, "Gauge")
    _generate_latest = getattr(_prometheus, "generate_latest")

CONTENT_TYPE_LATEST = _CONTENT_TYPE
generate_latest = _generate_latest

from .models import PhaseTiming


class MetricsExporter:
    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        self._phase_duration = Gauge(
            "xfs_scan_phase_duration_seconds",
            "Duration of the most recently completed scan per phase",
            ["phase"],
            registry=self.registry,
        )
        self._bytes_scanned = Gauge(
            "xfs_scan_bytes_last",
            "Total bytes processed in the most recently completed scan",
            registry=self.registry,
        )
        self._active_scans = Gauge(
            "xfs_active_scans",
            "Number of scans currently running",
            registry=self.registry,
        )
        self._completed_scans = Counter(
            "xfs_scans_completed_total",
            "Counter of completed scans",
            registry=self.registry,
        )

    def set_active_scans(self, count: int) -> None:
        self._active_scans.set(count)

    def record_scan(self, bytes_scanned: int, phase_timings: Iterable[PhaseTiming]) -> None:
        self._bytes_scanned.set(bytes_scanned)
        for timing in phase_timings:
            if timing.duration_seconds is not None:
                self._phase_duration.labels(phase=timing.phase).set(timing.duration_seconds)
        self._completed_scans.inc()

    def render(self) -> tuple[bytes, str]:
        payload = generate_latest(self.registry)
        return payload, CONTENT_TYPE_LATEST
