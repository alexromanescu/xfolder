from __future__ import annotations

import time

from app.config import AppConfig
from app.models import ScanRequest, ScanStatus
from app.store import ScanManager

from .test_similarity_groups import build_nested_x_tree


def _wait_for_completion(manager: ScanManager, scan_id: str, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        progress = manager.get_progress(scan_id)
        if progress.status == ScanStatus.COMPLETED:
            return
        time.sleep(0.05)
    raise TimeoutError("scan did not complete in time")


def test_group_contents_lists_folder_entries(tmp_path):
    root = build_nested_x_tree(tmp_path)

    request = ScanRequest(root_path=root)
    config = AppConfig(config_path=tmp_path / "config")
    manager = ScanManager(config, executor_workers=1)

    job = manager.start_scan(request)
    _wait_for_completion(manager, job.scan_id)

    groups = manager.get_groups(job.scan_id)
    assert groups, "expected similarity group"
    contents = manager.get_group_contents(job.scan_id, groups[0].group_id)

    assert contents.canonical.entries, "canonical entries should include files"
    assert any(entry.path.endswith("file.txt") for entry in contents.canonical.entries)
    assert contents.duplicates, "duplicate contents should be populated"
    duplicate_entries = contents.duplicates[0].entries
    assert any(entry.path.endswith("file.txt") for entry in duplicate_entries)

    manager.shutdown()
