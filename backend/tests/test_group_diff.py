from __future__ import annotations

import time
from pathlib import Path

from app.config import AppConfig
from app.models import ScanRequest, ScanStatus
from app.store import ScanManager


def test_group_diff_round_trip(tmp_path: Path) -> None:
    root = tmp_path / "diff_root"
    (root / "A").mkdir(parents=True, exist_ok=True)
    (root / "B").mkdir(parents=True, exist_ok=True)
    (root / "A" / "file.txt").write_bytes(b"same-content")
    (root / "B" / "file.txt").write_bytes(b"same-content")

    config_root = tmp_path / "config"
    config_root.mkdir(parents=True, exist_ok=True)

    app_config = AppConfig(
        config_path=config_root,
        cache_db_path=config_root / "cache.db",
        log_stream_enabled=False,
        metrics_enabled=False,
    )

    request = ScanRequest(root_path=root)
    manager = ScanManager(app_config, executor_workers=2)

    try:
        job = manager.start_scan(request)

        deadline = time.time() + 10
        while time.time() < deadline and job.status != ScanStatus.COMPLETED:
            time.sleep(0.05)

        assert job.status == ScanStatus.COMPLETED

        all_infos = [info for infos in job.group_infos.values() for info in infos]
        assert all_infos, "Expected at least one similarity group"

        label, info = next(iter(job.group_infos.items()))
        assert info, "Expected group info for label"
        group = info[0]
        assert len(group.members) >= 2

        left_member = group.members[0]
        right_member = group.members[1]

        diff = manager.get_group_diff(
            job.scan_id,
            group.group_id,
            left_member.relative_path,
            right_member.relative_path,
        )

        assert diff.left.relative_path == left_member.relative_path
        assert diff.right.relative_path == right_member.relative_path
        assert isinstance(diff.only_left, list)
        assert isinstance(diff.only_right, list)
        assert isinstance(diff.mismatched, list)
    finally:
        manager.shutdown()

