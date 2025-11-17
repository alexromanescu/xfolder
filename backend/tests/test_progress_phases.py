from __future__ import annotations

from datetime import datetime, timezone

from app.models import PhaseProgress, ScanRequest, ScanStatus
from app.store import AppConfig, ScanJob, ScanManager


def _make_manager(tmp_path) -> ScanManager:  # type: ignore[override]
  config = AppConfig(config_path=tmp_path / "config")
  return ScanManager(config, executor_workers=1)


def _register_job(manager: ScanManager, job: ScanJob) -> None:
  manager._jobs[job.scan_id] = job  # type: ignore[attr-defined]


def test_phases_during_walking(tmp_path):
  manager = _make_manager(tmp_path)
  request = ScanRequest(root_path=tmp_path)
  job = ScanJob("scan_walking", request)
  job.status = ScanStatus.RUNNING
  job.started_at = datetime.now(timezone.utc)
  job.stats["folders_scanned"] = 5
  job.stats["folders_discovered"] = 10
  job.meta["phase"] = "walking"
  _register_job(manager, job)

  progress = manager.get_progress(job.scan_id)
  phases = {phase.name: phase for phase in progress.phases}

  walking = phases["walking"]
  assert walking.status == "running"
  assert walking.progress and 0.4 < walking.progress < 0.6
  assert phases["aggregating"].status == "pending"
  assert phases["grouping"].status == "pending"


def test_phases_during_aggregating(tmp_path):
  manager = _make_manager(tmp_path)
  request = ScanRequest(root_path=tmp_path)
  job = ScanJob("scan_aggregating", request)
  job.status = ScanStatus.RUNNING
  job.started_at = datetime.now(timezone.utc)
  job.stats.update(
    {
      "folders_scanned": 10,
      "folders_discovered": 10,
      "total_folders": 20,
      "folders_aggregated": 10,
    }
  )
  job.meta["phase"] = "aggregating"
  _register_job(manager, job)

  progress = manager.get_progress(job.scan_id)
  phases = {phase.name: phase for phase in progress.phases}

  assert phases["walking"].status == "completed"
  aggregating = phases["aggregating"]
  assert aggregating.status == "running"
  assert aggregating.progress and 0.4 < aggregating.progress < 0.6
  assert phases["grouping"].status == "pending"


def test_phases_during_grouping(tmp_path):
  manager = _make_manager(tmp_path)
  request = ScanRequest(root_path=tmp_path)
  job = ScanJob("scan_grouping", request)
  job.status = ScanStatus.RUNNING
  job.started_at = datetime.now(timezone.utc)
  job.stats.update(
    {
      "folders_scanned": 10,
      "folders_discovered": 10,
      "total_folders": 10,
      "folders_aggregated": 10,
      "similarity_pairs_total": 100,
      "similarity_pairs_processed": 50,
    }
  )
  job.meta["phase"] = "grouping"
  _register_job(manager, job)

  progress = manager.get_progress(job.scan_id)
  phases = {phase.name: phase for phase in progress.phases}

  assert phases["walking"].status == "completed"
  assert phases["aggregating"].status == "completed"
  grouping = phases["grouping"]
  assert grouping.status == "running"
  assert grouping.progress and 0.4 < grouping.progress < 0.6

