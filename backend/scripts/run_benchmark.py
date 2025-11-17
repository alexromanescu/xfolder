#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import tracemalloc
from datetime import datetime, timezone
from statistics import fmean
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable, Set
import gc


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
from app.domain import FolderInfo  # noqa: E402
from app.store import ScanJob, ScanManager  # noqa: E402
from app.system import read_resource_stats  # noqa: E402


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
    parser.add_argument(
        "--include-matrix",
        action="store_true",
        help="Generate the similarity matrix during the benchmark",
    )
    parser.add_argument(
        "--include-treemap",
        action="store_true",
        help="Generate the duplicate-density treemap during the benchmark",
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=REPO_ROOT / "docs" / "benchmark-history",
        help="Directory where JSON summaries are stored per run (default: %(default)s)",
    )
    parser.add_argument(
        "--no-log",
        action="store_true",
        help="Skip writing JSON summaries to disk",
    )
    parser.add_argument(
        "--extra-sample-interval",
        type=float,
        default=0.0,
        help="Add an extra resource sampler that polls every N seconds (0 disables)",
    )
    parser.add_argument(
        "--profile-heap",
        action="store_true",
        help="Capture tracemalloc diffs to highlight top allocations",
    )
    parser.add_argument(
        "--phase-heap-snapshots",
        action="store_true",
        help="Capture tracemalloc stats once per phase (requires --profile-heap)",
    )
    parser.add_argument(
        "--object-census-interval",
        type=float,
        default=0.0,
        help="Collect GC object counts every N seconds (0 disables)",
    )
    parser.add_argument(
        "--smaps-interval",
        type=float,
        default=0.0,
        help="Record /proc/self/smaps_rollup every N seconds (0 disables)",
    )
    return parser.parse_args()


def wait_for_completion(
    manager: ScanManager,
    job: ScanJob,
    poll_interval: float,
    progress_callback: Optional[Callable[[ScanProgress], None]] = None,
) -> ScanJob:
    while True:
        progress = manager.get_progress(job.scan_id)
        if progress_callback:
            progress_callback(progress)
        if progress.status == ScanStatus.COMPLETED:
            return manager.get_job(job.scan_id)
        if progress.status == ScanStatus.FAILED:
            raise RuntimeError(f"Scan {job.scan_id} failed: {job.error}")
        time.sleep(poll_interval)


class ExtraResourceSampler:
    def __init__(self, interval: float) -> None:
        self.interval = interval
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._records: List[Dict[str, Any]] = []

    def start(self) -> None:
        if self.interval <= 0:
            return

        def _loop():
            while not self._stop.is_set():
                stats = read_resource_stats()
                self._records.append(
                    {
                        "timestamp": datetime.now(timezone.utc),
                        "rss_bytes": stats.process_rss_bytes,
                        "cpu_cores": stats.cpu_cores,
                        "load_1m": stats.load_1m,
                        "read_bytes": stats.process_read_bytes,
                        "write_bytes": stats.process_write_bytes,
                    }
                )
                self._stop.wait(self.interval)

        self._thread = threading.Thread(target=_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if not self._thread:
            return
        self._stop.set()
        self._thread.join()

    def samples(self) -> List[Dict[str, Any]]:
        return self._records


class ObjectCensusSampler:
    def __init__(self, interval: float) -> None:
        self.interval = interval
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._records: List[Dict[str, Any]] = []

    def start(self) -> None:
        if self.interval <= 0:
            return

        def _loop():
            from app.models import FolderRecord, GroupRecord, DirectoryFingerprint  # noqa: E402

            while not self._stop.is_set():
                gc.collect()
                counts = {
                    "FolderRecord": 0,
                    "GroupRecord": 0,
                    "DirectoryFingerprint": 0,
                    "FolderInfo": 0,
                    "Path": 0,
                }
                for obj in gc.get_objects():
                    try:
                        if isinstance(obj, FolderRecord):
                            counts["FolderRecord"] += 1
                        elif isinstance(obj, GroupRecord):
                            counts["GroupRecord"] += 1
                        elif isinstance(obj, DirectoryFingerprint):
                            counts["DirectoryFingerprint"] += 1
                        elif isinstance(obj, FolderInfo):
                            counts["FolderInfo"] += 1
                        elif isinstance(obj, Path):
                            counts["Path"] += 1
                    except ReferenceError:
                        continue
                self._records.append(
                    {
                        "timestamp": datetime.now(timezone.utc),
                        "counts": counts,
                    }
                )
                self._stop.wait(self.interval)

        self._thread = threading.Thread(target=_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if not self._thread:
            return
        self._stop.set()
        self._thread.join()

    def samples(self) -> List[Dict[str, Any]]:
        return self._records


class SmapsSampler:
    def __init__(self, interval: float) -> None:
        self.interval = interval
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._records: List[Dict[str, Any]] = []

    def start(self) -> None:
        if self.interval <= 0:
            return

        def _loop():
            while not self._stop.is_set():
                stats = self._read()
                stats["timestamp"] = datetime.now(timezone.utc)
                self._records.append(stats)
                self._stop.wait(self.interval)

        self._thread = threading.Thread(target=_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if not self._thread:
            return
        self._stop.set()
        self._thread.join()

    def samples(self) -> List[Dict[str, Any]]:
        return self._records

    @staticmethod
    def _read() -> Dict[str, Any]:
        stats: Dict[str, Any] = {}
        try:
            with open("/proc/self/smaps_rollup", "r", encoding="utf-8") as fh:
                for line in fh:
                    if ":" not in line:
                        continue
                    key, value = line.split(":", 1)
                    parts = value.strip().split()
                    if len(parts) >= 1 and parts[0].isdigit():
                        stats[key.strip().lower()] = int(parts[0])
        except OSError:
            stats["error"] = "unavailable"
        return stats


def _phase_for_timestamp(job: ScanJob, timestamp) -> Optional[str]:
    for name in job.phase_sequence:
        timing = job.phase_timings.get(name)
        if not timing:
            continue
        start = timing.started_at
        end = timing.completed_at or timestamp
        if start <= timestamp <= end:
            return name
    return None


def collect_structure_metrics(job: ScanJob) -> Dict[str, Any]:
    metrics: Dict[str, Any] = {}
    all_infos: List[Any] = []
    for records in getattr(job, "group_infos", {}).values():
        all_infos.extend(records)
    metrics["group_records"] = len(all_infos)
    metrics["group_members_total"] = sum(len(info.members) for info in all_infos)
    metrics["group_pairwise_entries"] = sum(len(info.pairwise_similarity) for info in all_infos)
    metrics["group_divergence_entries"] = sum(len(info.divergences) for info in all_infos)
    metrics["matrix_entries"] = len(job.matrix_entries)
    fingerprint_count = 0
    if job.result and getattr(job.result, "fingerprints", None):
        fingerprint_count = len(job.result.fingerprints)
    metrics["fingerprint_count"] = fingerprint_count
    return metrics


class PhaseHeapProfiler:
    def __init__(self, enabled: bool, base_snapshot) -> None:
        self.enabled = enabled and base_snapshot is not None
        self.base_snapshot = base_snapshot
        self.records: Dict[str, List[Dict[str, Any]]] = {}
        self._seen: Set[str] = set()

    def capture(self, phase: str) -> None:
        if not self.enabled or not phase or phase in self._seen:
            return
        snapshot = tracemalloc.take_snapshot()
        stats = snapshot.compare_to(self.base_snapshot, "lineno")[:10]
        self.records[phase] = [
            {
                "location": f"{stat.traceback[0].filename}:{stat.traceback[0].lineno}",
                "size_bytes": stat.size,
                "count": stat.count,
            }
            for stat in stats
        ]
        self._seen.add(phase)


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

    samples_detail: List[Dict[str, Any]] = []
    phase_peaks: Dict[str, Dict[str, Any]] = {}
    for sample in job.resource_samples:
        if sample.process_rss_bytes is None:
            continue
        offset = None
        if job.started_at:
            offset = (sample.timestamp - job.started_at).total_seconds()
        phase_name = _phase_for_timestamp(job, sample.timestamp)
        entry = {
            "timestamp": sample.timestamp.isoformat(),
            "seconds_since_start": offset,
            "phase": phase_name,
            "rss_bytes": sample.process_rss_bytes,
            "rss_mebibytes": sample.process_rss_bytes / (1024 ** 2),
            "cpu_cores": sample.cpu_cores,
            "load_1m": sample.load_1m,
            "read_bytes": sample.process_read_bytes,
            "write_bytes": sample.process_write_bytes,
        }
        samples_detail.append(entry)
        if phase_name:
            prev = phase_peaks.get(phase_name)
            if not prev or entry["rss_bytes"] > prev["rss_bytes"]:
                phase_peaks[phase_name] = entry

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
        "resource_samples_detail": samples_detail,
        "phase_memory_peaks": phase_peaks,
    }


def save_summary(summary: Dict[str, Any], job: ScanJob, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    started_at = job.started_at.isoformat().replace(":", "").replace("-", "").replace("+", "").replace(".", "")
    filename = f"{job.scan_id}_{started_at}.json"
    path = directory / filename
    path.write_text(json.dumps(summary, indent=2))
    return path


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
    structure = summary.get("structure_metrics") or {}
    if structure:
        print("Structure metrics:")
        for key, value in structure.items():
            print(f"  - {key}: {value}")
    peak = summary.get("peak_rss_mebibytes")
    if peak is not None:
        print(f"Peak RSS: {peak:.2f} MiB")
    avg = summary.get("average_rss_bytes")
    if avg is not None:
        print(f"Average RSS: {avg / (1024 ** 2):.2f} MiB")
    peaks = summary.get("phase_memory_peaks") or {}
    if peaks:
        print("Phase memory peaks:")
        for phase, entry in peaks.items():
            rss = entry["rss_mebibytes"]
            offset = entry.get("seconds_since_start")
            if rss is None:
                continue
            offset_text = f"{offset:.2f}s" if isinstance(offset, (int, float)) else "n/a"
            print(f"  - {phase}: {rss:.2f} MiB at +{offset_text}")
    samples = summary.get("resource_samples_detail") or []
    if samples:
        print("Resource samples timeline:")
        for entry in samples:
            rss = entry["rss_mebibytes"]
            offset = entry.get("seconds_since_start")
            offset_text = f"{offset:.2f}s" if isinstance(offset, (int, float)) else "n/a"
            phase_name = entry.get("phase") or "unknown"
            print(f"  - +{offset_text} [{phase_name}] {rss:.2f} MiB (load {entry['load_1m']:.2f})")
    extra_samples = summary.get("extra_resource_samples") or []
    if extra_samples:
        print("High-frequency samples:")
        for entry in extra_samples:
            rss = entry.get("rss_mebibytes")
            if rss is None:
                continue
            offset = entry.get("seconds_since_start")
            offset_text = f"{offset:.2f}s" if isinstance(offset, (int, float)) else "n/a"
            phase_name = entry.get("phase") or "unknown"
            print(f"  - +{offset_text} [{phase_name}] {rss:.2f} MiB (load {entry.get('load_1m', 0):.2f})")
    census = summary.get("object_census") or []
    if census:
        print("Object census timeline:")
        for entry in census:
            offset = entry.get("seconds_since_start")
            offset_text = f"{offset:.2f}s" if isinstance(offset, (int, float)) else "n/a"
            counts = entry.get("counts", {})
            print(
                "  - +{offset} FolderRecord={fr} FolderInfo={fi} GroupRecord={gr} DirectoryFingerprint={df} Path={pth}".format(
                    offset=offset_text,
                    fr=counts.get("FolderRecord", 0),
                    fi=counts.get("FolderInfo", 0),
                    gr=counts.get("GroupRecord", 0),
                    df=counts.get("DirectoryFingerprint", 0),
                    pth=counts.get("Path", 0),
                )
            )
    smaps = summary.get("smaps_samples") or []
    if smaps:
        print("smaps_rollup samples:")
        for entry in smaps:
            offset = entry.get("seconds_since_start")
            offset_text = f"{offset:.2f}s" if isinstance(offset, (int, float)) else "n/a"
            rss_kb = entry.get("rss")
            rss_mb = (rss_kb / 1024) if isinstance(rss_kb, (int, float)) else None
            rss_text = f"{rss_mb:.2f} MiB" if rss_mb is not None else "n/a"
            print(f"  - +{offset_text} RSS={rss_text} entries={len(entry.keys())}")
    heap_entries = summary.get("heap_profile") or []
    if heap_entries:
        print("Heap profile (top allocations):")
        for stat in heap_entries:
            size_mb = stat["size_bytes"] / (1024 ** 2)
            print(f"  - {stat['location']}: {size_mb:.2f} MiB across {stat['count']} allocations")
    phase_heaps = summary.get("phase_heap_profile") or {}
    if phase_heaps:
        print("Per-phase heap snapshots:")
        for phase, stats in phase_heaps.items():
            print(f"  Phase {phase}:")
            for stat in stats:
                size_mb = stat["size_bytes"] / (1024 ** 2)
                print(f"    - {stat['location']}: {size_mb:.2f} MiB ({stat['count']} allocs)")


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
        include_matrix=args.include_matrix,
        include_treemap=args.include_treemap,
    )

    manager = ScanManager(app_config, executor_workers=args.workers)
    tracer_base = None
    if args.profile_heap or args.phase_heap_snapshots:
        tracemalloc.start()
        tracer_base = tracemalloc.take_snapshot()
    phase_profiler = PhaseHeapProfiler(args.phase_heap_snapshots, tracer_base)
    extra_sampler = ExtraResourceSampler(args.extra_sample_interval)
    extra_sampler.start()
    object_sampler = ObjectCensusSampler(args.object_census_interval)
    object_sampler.start()
    smaps_sampler = SmapsSampler(args.smaps_interval)
    smaps_sampler.start()
    try:
        job = manager.start_scan(request)
        last_phase: Optional[str] = None

        def progress_hook(progress):
            nonlocal last_phase
            if progress.phase and progress.phase != last_phase:
                phase_profiler.capture(progress.phase)
                last_phase = progress.phase

        final_job = wait_for_completion(
            manager,
            job,
            args.poll_interval,
            progress_callback=progress_hook if (args.phase_heap_snapshots and tracer_base) else None,
        )
    finally:
        extra_sampler.stop()
        object_sampler.stop()
        smaps_sampler.stop()
        manager.shutdown()
    heap_snapshot = None
    if args.profile_heap or args.phase_heap_snapshots:
        heap_snapshot = tracemalloc.take_snapshot()
        tracemalloc.stop()

    if final_job.status != ScanStatus.COMPLETED:
        raise SystemExit(f"Scan {final_job.scan_id} did not complete successfully.")

    summary = summarize(final_job)
    summary["structure_metrics"] = collect_structure_metrics(final_job)
    if phase_profiler.records:
        summary["phase_heap_profile"] = phase_profiler.records
    extra_records = []
    for entry in extra_sampler.samples():
        timestamp = entry["timestamp"]
        offset = None
        if final_job.started_at:
            offset = (timestamp - final_job.started_at).total_seconds()
        phase_name = _phase_for_timestamp(final_job, timestamp)
        rss = entry["rss_bytes"]
        extra_records.append(
            {
                "timestamp": timestamp.isoformat(),
                "seconds_since_start": offset,
                "phase": phase_name,
                "rss_bytes": rss,
                "rss_mebibytes": rss / (1024 ** 2) if rss is not None else None,
                "cpu_cores": entry["cpu_cores"],
                "load_1m": entry["load_1m"],
                "read_bytes": entry["read_bytes"],
                "write_bytes": entry["write_bytes"],
            }
        )
    summary["extra_resource_samples"] = extra_records
    census_records = []
    for entry in object_sampler.samples():
        timestamp = entry["timestamp"]
        offset = (timestamp - final_job.started_at).total_seconds() if final_job.started_at else None
        census_records.append(
            {
                "timestamp": timestamp.isoformat(),
                "seconds_since_start": offset,
                "counts": entry["counts"],
            }
        )
    summary["object_census"] = census_records
    smaps_records = []
    for entry in smaps_sampler.samples():
        timestamp = entry.get("timestamp")
        offset = (timestamp - final_job.started_at).total_seconds() if final_job.started_at and timestamp else None
        record = {k: v for k, v in entry.items() if k != "timestamp"}
        record["timestamp"] = timestamp.isoformat() if timestamp else None
        record["seconds_since_start"] = offset
        smaps_records.append(record)
    summary["smaps_samples"] = smaps_records
    if args.profile_heap and heap_snapshot and tracer_base:
        stats = heap_snapshot.compare_to(tracer_base, "lineno")[:10]
        summary["heap_profile"] = [
            {
                "location": f"{stat.traceback[0].filename}:{stat.traceback[0].lineno}",
                "size_bytes": stat.size,
                "count": stat.count,
            }
            for stat in stats
        ]

    print_summary(summary)
    if args.json_output:
        print(json.dumps(summary, indent=2))
    if not args.no_log:
        log_path = save_summary(summary, final_job, args.log_dir)
        print(f"Saved benchmark log to {log_path}")


if __name__ == "__main__":
    main()
