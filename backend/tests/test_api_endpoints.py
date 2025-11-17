from __future__ import annotations

import logging
import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

CONFIG_ROOT = Path(__file__).resolve().parents[2] / ".config-test"
os.environ.setdefault("XFS_CONFIG_PATH", str(CONFIG_ROOT))

import app.main as main_app
from app.logstream import LogStreamHandler
from app.main import app, get_scan_manager
from app.models import (
    FolderLabel,
    FolderRecord,
    PhaseTiming,
    ResourceSample,
    ScanMetrics,
    SimilarityMatrixEntry,
    SimilarityMatrixResponse,
    TreemapNode,
    TreemapResponse,
)


class _StubScanManager:
    def __init__(self) -> None:
        left = FolderRecord(
            path="/data/canonical",
            relative_path="canonical",
            total_bytes=200,
            file_count=12,
            unstable=False,
        )
        right = FolderRecord(
            path="/data/duplicate",
            relative_path="duplicate",
            total_bytes=120,
            file_count=10,
            unstable=False,
        )
        entry = SimilarityMatrixEntry(
            group_id="g_matrix",
            label=FolderLabel.NEAR_DUPLICATE,
            left=left,
            right=right,
            similarity=0.9,
            combined_bytes=320,
            reclaimable_bytes=120,
        )
        generated_at = datetime.now(timezone.utc)
        self.matrix_response = SimilarityMatrixResponse(
            scan_id="scan-demo",
            generated_at=generated_at,
            root_path=Path("/data"),
            min_similarity=0.6,
            total_entries=1,
            entries=[entry],
        )
        self.treemap_response = TreemapResponse(
            scan_id="scan-demo",
            generated_at=generated_at,
            root_path=Path("/data"),
            tree=TreemapNode(
                path=".",
                name="data",
                total_bytes=1000,
                duplicate_bytes=300,
                identical_groups=2,
                near_groups=3,
                children=[
                    TreemapNode(
                        path="albums",
                        name="albums",
                        total_bytes=600,
                        duplicate_bytes=200,
                        identical_groups=1,
                        near_groups=1,
                        children=[],
                    )
                ],
            ),
        )
        self.matrix_calls: list[tuple[str, float, int, int]] = []
        self.treemap_calls: list[str] = []
        sample = ResourceSample(
            timestamp=generated_at,
            cpu_cores=8,
            load_1m=0.5,
            process_rss_bytes=1024,
            process_read_bytes=None,
            process_write_bytes=None,
        )
        timing = PhaseTiming(phase="walking", started_at=generated_at, completed_at=generated_at, duration_seconds=0.1)
        self.metrics_response = ScanMetrics(
            scan_id="scan-demo",
            root_path=Path("/data"),
            started_at=generated_at,
            completed_at=generated_at,
            worker_count=4,
            bytes_scanned=320,
            phase_timings=[timing],
            resource_samples=[sample],
        )

    def get_similarity_matrix(self, scan_id: str, *, min_similarity: float, limit: int, offset: int):
        self.matrix_calls.append((scan_id, min_similarity, limit, offset))
        return self.matrix_response

    def get_treemap(self, scan_id: str):
        self.treemap_calls.append(scan_id)
        return self.treemap_response

    def get_metrics(self, scan_id: str):
        return self.metrics_response


def _override_manager(stub: _StubScanManager):
    original = app.dependency_overrides.get(get_scan_manager)
    app.dependency_overrides[get_scan_manager] = lambda: stub
    return original


def _restore_manager(original):
    if original is None:
        app.dependency_overrides.pop(get_scan_manager, None)
    else:
        app.dependency_overrides[get_scan_manager] = original


def test_similarity_matrix_endpoint_honors_filters():
    stub = _StubScanManager()
    previous = _override_manager(stub)
    client = TestClient(app)
    try:
        response = client.get(
            "/api/scans/scan-demo/matrix",
            params={"min_similarity": 0.8, "limit": 5, "offset": 2},
        )
        assert response.status_code == 200
        assert stub.matrix_calls == [("scan-demo", 0.8, 5, 2)]
        payload = response.json()
        assert payload["entries"][0]["left"]["relative_path"] == "canonical"
        assert payload["entries"][0]["similarity"] == pytest.approx(0.9)
    finally:
        _restore_manager(previous)


def test_treemap_endpoint_returns_tree():
    stub = _StubScanManager()
    previous = _override_manager(stub)
    client = TestClient(app)
    try:
        response = client.get("/api/scans/scan-demo/density/treemap")
        assert response.status_code == 200
        assert stub.treemap_calls == ["scan-demo"]
        tree = response.json()["tree"]
        assert tree["duplicate_bytes"] == 300
        assert tree["children"][0]["name"] == "albums"
    finally:
        _restore_manager(previous)


def test_scan_metrics_endpoint_returns_timings():
    stub = _StubScanManager()
    previous = _override_manager(stub)
    client = TestClient(app)
    try:
        response = client.get("/api/scans/scan-demo/metrics")
        assert response.status_code == 200
        payload = response.json()
        assert payload["bytes_scanned"] == 320
        assert payload["phase_timings"][0]["phase"] == "walking"
    finally:
        _restore_manager(previous)


def test_resource_stats_endpoint_reports_fields():
    client = TestClient(app)
    response = client.get("/api/system/resources")
    assert response.status_code == 200
    payload = response.json()
    assert payload["cpu_cores"] >= 1
    assert "process_rss_bytes" in payload


def test_log_stream_endpoint_streams_history(monkeypatch):
    handler = LogStreamHandler()
    record = logging.LogRecord(
        name="xfolder.tests",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="stream-ready",
        args=(),
        exc_info=None,
    )
    handler.emit(record)
    monkeypatch.setattr(main_app, "log_stream_handler", handler)
    monkeypatch.setattr(main_app.config, "log_stream_enabled", True, raising=False)

    client = TestClient(main_app.app)
    with client.stream("GET", "/api/system/logs/stream", params={"once": "true"}) as response:
        assert response.status_code == 200
        text_iter = response.iter_text()
        first_chunk = next(text_iter)
        assert "stream-ready" in first_chunk


def test_progress_stream_endpoint_uses_history(monkeypatch):
    queue: asyncio.Queue[str] = asyncio.Queue()

    class StubProgressStream:
        def subscribe(self):
            return (queue, asyncio.get_event_loop())

        def unsubscribe(self, _subscriber):
            pass

        def history(self):
            return ['{"type":"scan_progress","scans":[]}']

    monkeypatch.setattr(main_app, "progress_stream", StubProgressStream())
    client = TestClient(main_app.app)
    with client.stream("GET", "/api/scans/events", params={"once": "true"}) as response:
        assert response.status_code == 200
        chunk = next(response.iter_text())
        assert "scan_progress" in chunk


def test_metrics_endpoint(monkeypatch):
    class StubExporter:
        def render(self):
            return b"metric 1", "text/plain"

    monkeypatch.setattr(main_app, "metrics_exporter", StubExporter())
    monkeypatch.setattr(main_app.config, "metrics_enabled", True, raising=False)
    client = TestClient(main_app.app)
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "metric" in response.text
