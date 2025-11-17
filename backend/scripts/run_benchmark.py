#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from statistics import fmean
from pathlib import Path
from typing import Any, Dict, List


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import AppConfig  # noqa: E402
from app.models import (  # noqa: E402
    FileEqualityMode,
    ScanRequest,
    ScanStatus,
    StructurePolicy,
)
from app.store import ScanJob, ScanManager  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a headless benchmark of the Folder Similarity Scanner.",
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=REPO_ROOT / "test_mockup",
        help="Directory to scan (default: %(default)s)",
    )
    parser.add_argument(
        "--config-dir",
        type=Path,
        default=REPO_ROOT / ".benchmark-config",
        help="Where to store ephemeral benchmark config/cache (default: %(default)s)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Thread pool size for the ScanManager (default: %(default)s)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=None,
        help="Optional override for scanner concurrency",
    )
    parser.add_argument(
        "--similarity-threshold",
        type=float,
        default=0.80,
        help="Similarity threshold to use during benchmarking (default: %(default)s)",
    )
    parser.add_argument(
        "--file-equality",
        type=str,
        choices=[mode.value for mode in FileEqualityMode],
        default=FileEqualityMode.NAME_SIZE.value,
        help="File equality mode (default: %(default)s)",
    )
    parser.add_argument(
        "--structure-policy",
        type=str,
        choices=[policy.value for policy in StructurePolicy],
        default=StructurePolicy.RELATIVE.value,
        help="Structure policy (default: %(default)s)",
    )
    parser.add_argument(
        "--force-case-insensitive",
        action="store_true",
        help="Force case-insensitive comparisons",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=0.5,
        help="Seconds between progress polls (default: %(default)s)",
    )
    parser.add_argument(
        "--json-output",
        action="store_true",
        help="Emit the summary as formatted JSON in addition to the text table",
    )
    return parser.parse_args()


def wait_for_completion(manager: ScanManager, job: ScanJob, poll_interval: float) -> ScanJob:
    while True:
        progress = manager.get_progress(job.scan_id)
        if progress.status == ScanStatus.COMPLETED:
            return manager.get_job(job.scan_id)
        if progress.status == ScanStatus.FAILED:
            raise RuntimeError(f"Scan {job.scan_id} failed: {job.error}")
        time.sleep(poll_interval)


def summarize(job: ScanJob) -> Dict[str, Any]:
    total_duration = None
    if job.completed_at and job.started_at:
        total_duration = (job.completed_at - job.started_at).total_seconds()

    phases: List[Dict[str, Any]] = []
    for name in job.phase_sequence:
        timing = job.phase_timings.get(name)
        if not timing:
            continue
        duration = timing.duration_seconds
        if duration is None and timing.completed_at and timing.started_at:
            duration = (timing.completed_at - timing.started_at).total_seconds()
        phases.append(
            {
                "phase": name,
                "started_at": timing.started_at.isoformat(),
                "completed_at": timing.completed_at.isoformat() if timing.completed_at else None,
                "duration_seconds": duration,
            }
        )

    rss_samples = [
        sample.process_rss_bytes
        for sample in job.resource_samples
        if getattr(sample, "process_rss_bytes", None)
    ]
    peak_rss = max(rss_samples) if rss_samples else None
    avg_rss = fmean(rss_samples) if rss_samples else None

    return {
        "scan_id": job.scan_id,
        "root_path": str(job.request.root_path),
        "started_at": job.started_at.isoformat(),
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "total_duration_seconds": total_duration,
        "stats": dict(job.stats),
        "phase_timings": phases,
        "resource_samples": len(job.resource_samples),
        "peak_rss_bytes": peak_rss,
        "peak_rss_mebibytes": peak_rss / (1024 ** 2) if peak_rss else None,
        "average_rss_bytes": avg_rss,
    }


def print_summary(summary: Dict[str, Any]) -> None:
    print("=== Folder Similarity Scanner Benchmark ===")
    print(f"Scan ID: {summary['scan_id']}")
    print(f"Root Path: {summary['root_path']}")
    if summary["total_duration_seconds"] is not None:
        print(f"Total Duration: {summary['total_duration_seconds']:.2f}s")
    stats = summary.get("stats") or {}
    print(
        "Stats: files={files} folders={folders} discovered={discovered}".format(
            files=stats.get("files_scanned", 0),
            folders=stats.get("folders_scanned", 0),
            discovered=stats.get("folders_discovered", 0),
        )
    )
    print("Phase Timings:")
    for phase in summary["phase_timings"]:
        duration = phase["duration_seconds"]
        duration_text = f"{duration:.2f}s" if duration is not None else "n/a"
        print(f"  - {phase['phase']}: {duration_text}")
    peak = summary.get("peak_rss_mebibytes")
    if peak is not None:
        print(f"Peak RSS: {peak:.2f} MiB")
    avg = summary.get("average_rss_bytes")
    if avg is not None:
        print(f"Average RSS: {avg / (1024 ** 2):.2f} MiB")


def main() -> None:
    args = parse_args()
    target = args.target.resolve()
    if not target.exists():
        raise SystemExit(f"Target folder not found: {target}")

    config_dir = args.config_dir.resolve()
    config_dir.mkdir(parents=True, exist_ok=True)

    cache_db = config_dir / "cache.db"
    app_config = AppConfig(
        config_path=config_dir,
        cache_db_path=cache_db,
        log_stream_enabled=False,
        metrics_enabled=False,
    )

    request = ScanRequest(
        root_path=target,
        include=[],
        exclude=[],
        similarity_threshold=args.similarity_threshold,
        file_equality=FileEqualityMode(args.file_equality),
        structure_policy=StructurePolicy(args.structure_policy),
        force_case_insensitive=args.force_case_insensitive,
        concurrency=args.concurrency,
        deletion_enabled=False,
    )

    manager = ScanManager(app_config, executor_workers=args.workers)
    try:
        job = manager.start_scan(request)
        final_job = wait_for_completion(manager, job, args.poll_interval)
    finally:
        manager.shutdown()

    if final_job.status != ScanStatus.COMPLETED:
        raise SystemExit(f"Scan {final_job.scan_id} did not complete successfully.")

    summary = summarize(final_job)
    print_summary(summary)
    if args.json_output:
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
