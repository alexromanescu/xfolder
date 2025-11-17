from __future__ import annotations

from typing import Iterable

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge, generate_latest

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
