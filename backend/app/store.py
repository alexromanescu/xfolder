from __future__ import annotations

import csv
import io
import json
import shutil
import threading
import uuid
from collections import defaultdict
import fnmatch
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from fastapi import HTTPException, status

from .analytics import build_similarity_matrix, build_treemap
from .cache import FileHashCache
from .config import AppConfig
from .models import (
    DeletionPlan,
    DeletionPlanPayload,
    DeletionResult,
    DiffEntry,
    ExportFilters,
    ExportHeader,
    FolderLabel,
    FolderEntry,
    GroupContents,
    GroupDiff,
    GroupRecord,
    MemberContents,
    MismatchEntry,
    PhaseProgress,
    PhaseTiming,
    ScanProgress,
    ScanRequest,
    ScanStatus,
    ScanMetrics,
    SimilarityMatrixEntry,
    SimilarityMatrixResponse,
    TreemapNode,
    TreemapResponse,
    WarningRecord,
    WarningType,
)
from .scanner import (
    FolderScanner,
    ScanResult,
    _identity_to_path,
    compute_fingerprint_diff,
    compute_similarity_groups,
    group_to_record,
)
from .metrics import MetricsExporter
from .system import read_resource_sample


class ScanJob:
    def __init__(self, scan_id: str, request: ScanRequest) -> None:
        self.scan_id = scan_id
        self.request = request
        self.status = ScanStatus.PENDING
        self.started_at = datetime.now(timezone.utc)
        self.completed_at: Optional[datetime] = None
        self.warnings: List[WarningRecord] = []
        self.stats: Dict[str, int] = {
            "files_scanned": 0,
            "folders_scanned": 0,
            "folders_discovered": 0,
            "workers": 0,
        }
        self.result: Optional[ScanResult] = None
        self.groups: Dict[FolderLabel, List[GroupRecord]] = defaultdict(list)
        self.error: Optional[str] = None
        self.meta: Dict[str, str] = {"phase": "", "last_path": ""}
        self.matrix_entries: List[SimilarityMatrixEntry] = []
        self.treemap: Optional[TreemapNode] = None
        self.phase_timings: Dict[str, PhaseTiming] = {}
        self.phase_sequence: List[str] = []
        self._current_phase: Optional[str] = None
        self.resource_samples: List[ResourceSample] = []

    def set_phase(self, name: str) -> None:
        if self._current_phase == name:
            return
        if self._current_phase:
            self.finish_phase(self._current_phase)
        now = datetime.now(timezone.utc)
        timing = PhaseTiming(phase=name, started_at=now)
        self.phase_timings[name] = timing
        self.phase_sequence.append(name)
        self._current_phase = name
        self.capture_resource_sample()

    def finish_phase(self, name: Optional[str] = None) -> None:
        target = name or self._current_phase
        if not target:
            return
        timing = self.phase_timings.get(target)
        if timing and timing.completed_at is None:
            now = datetime.now(timezone.utc)
            timing.completed_at = now
            timing.duration_seconds = (now - timing.started_at).total_seconds()
        if name is None or target == self._current_phase:
            self._current_phase = None
        self.capture_resource_sample()

    def handle_phase_transition(self, name: str) -> None:
        self.set_phase(name)

    def capture_resource_sample(self) -> None:
        sample = read_resource_sample()
        self.resource_samples.append(sample)


class ScanManager:
    def __init__(
        self,
        app_config: AppConfig,
        executor_workers: int = 4,
        metrics_exporter: Optional[MetricsExporter] = None,
    ) -> None:
        self.config = app_config
        cache_path = (
            app_config.cache_db_path
            if app_config.cache_db_path
            else app_config.config_path / "cache.db"
        )
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.file_cache = FileHashCache(cache_path)
        self._jobs: Dict[str, ScanJob] = {}
        self._plans: Dict[str, DeletionPlan] = {}
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutorWithStop(max_workers=executor_workers)
        self._metrics = metrics_exporter

    def start_scan(self, request: ScanRequest) -> ScanJob:
        scan_id = uuid.uuid4().hex[:12]
        job = ScanJob(scan_id, request)
        with self._lock:
            self._jobs[scan_id] = job
        self._executor.submit(self._run_scan, job)
        return job

    def shutdown(self) -> None:
        self._executor.shutdown()

    def list_jobs(self) -> List[ScanJob]:
        with self._lock:
            return list(self._jobs.values())

    def get_job(self, scan_id: str) -> ScanJob:
        with self._lock:
            if scan_id not in self._jobs:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scan not found")
            return self._jobs[scan_id]

    def get_progress(self, scan_id: str) -> ScanProgress:
        job = self.get_job(scan_id)
        stats_snapshot = dict(job.stats)
        progress = None
        eta_seconds = None
        now = datetime.now(timezone.utc)

        walking_ratio = None
        aggregating_ratio = None
        grouping_ratio = None
        scanned = stats_snapshot.get("folders_scanned", 0)
        discovered = stats_snapshot.get("folders_discovered", 0)
        discovered = max(discovered, scanned if scanned > 0 else 1)
        if discovered > 0:
            walking_ratio = scanned / discovered

        total_folders = stats_snapshot.get("total_folders", 0)
        folders_aggregated = stats_snapshot.get("folders_aggregated", 0)
        if total_folders > 0:
            aggregating_ratio = min(1.0, max(0.0, folders_aggregated / total_folders))

        pairs_total = stats_snapshot.get("similarity_pairs_total", 0)
        pairs_processed = stats_snapshot.get("similarity_pairs_processed", 0)
        if pairs_total > 0:
            grouping_ratio = min(1.0, max(0.0, pairs_processed / pairs_total))

        if job.status == ScanStatus.COMPLETED:
            progress = 1.0
            eta_seconds = 0
        elif job.status == ScanStatus.RUNNING:
            # Blend the three phases into a single progress estimate.
            # Walking: 40%, Aggregation: 30%, Grouping: 30%.
            overall = 0.0
            if walking_ratio is not None:
                overall += 0.4 * walking_ratio
            if aggregating_ratio is not None:
                overall += 0.3 * aggregating_ratio
            if grouping_ratio is not None:
                overall += 0.3 * grouping_ratio
            if overall > 0:
                progress = max(0.05, min(0.99, overall))
            elapsed = (now - job.started_at).total_seconds()
            if elapsed > 0 and scanned > 0:
                rate = scanned / elapsed
                remaining = max(discovered - scanned, 0)
                if rate > 0:
                    eta_seconds = int(remaining / rate)

        phases: List[PhaseProgress] = []
        current_phase = job.meta.get("phase", "")
        phase_names = ["walking", "aggregating", "grouping"]

        def phase_status(name: str) -> tuple[str, float | None]:
            if job.status == ScanStatus.COMPLETED:
                return "completed", 1.0
            if job.status == ScanStatus.PENDING:
                return "pending", 0.0
            if current_phase == name:
                if name == "walking" and walking_ratio is not None:
                    return "running", walking_ratio
                if name == "aggregating" and aggregating_ratio is not None:
                    return "running", aggregating_ratio
                if name == "grouping" and grouping_ratio is not None:
                    return "running", grouping_ratio
                return "running", None
            # Determine ordering by index in phase_names
            try:
                idx = phase_names.index(name)
                cur_idx = phase_names.index(current_phase) if current_phase in phase_names else -1
            except ValueError:
                return "pending", 0.0
            if cur_idx > idx:
                return "completed", 1.0
            return "pending", 0.0

        for name in phase_names:
            status, phase_progress = phase_status(name)
            phases.append(
                PhaseProgress(
                    name=name,
                    status=status,
                    progress=phase_progress,
                )
            )

        return ScanProgress(
            scan_id=job.scan_id,
            status=job.status,
            started_at=job.started_at,
            completed_at=job.completed_at,
            warnings=job.warnings,
            root_path=job.request.root_path,
            stats=stats_snapshot,
            progress=progress,
            eta_seconds=eta_seconds,
            phase=job.meta.get("phase", ""),
            last_path=job.meta.get("last_path") or None,
            phases=phases,
            include_matrix=job.request.include_matrix,
            include_treemap=job.request.include_treemap,
        )

    def get_groups(self, scan_id: str, label: Optional[FolderLabel] = None) -> List[GroupRecord]:
        job = self.get_job(scan_id)
        if job.status != ScanStatus.COMPLETED:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Scan is not complete")
        if label:
            return job.groups.get(label, [])
        groups: List[GroupRecord] = []
        for records in job.groups.values():
            groups.extend(records)
        return groups

    def get_similarity_matrix(
        self,
        scan_id: str,
        *,
        min_similarity: float,
        limit: int,
        offset: int,
    ) -> SimilarityMatrixResponse:
        job = self.get_job(scan_id)
        if job.status != ScanStatus.COMPLETED:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Scan is not complete")
        if not job.request.include_matrix:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Similarity matrix disabled for this scan")
        entries = [entry for entry in job.matrix_entries if entry.similarity >= min_similarity]
        total = len(entries)
        window = entries[offset : offset + limit]
        return SimilarityMatrixResponse(
            scan_id=scan_id,
            generated_at=datetime.now(timezone.utc),
            root_path=job.request.root_path,
            min_similarity=min_similarity,
            total_entries=total,
            entries=window,
        )

    def get_treemap(self, scan_id: str) -> TreemapResponse:
        job = self.get_job(scan_id)
        if job.status != ScanStatus.COMPLETED:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Scan is not complete")
        if not job.request.include_treemap:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Treemap disabled for this scan")
        if not job.treemap:
            job.treemap = TreemapNode(
                path=".",
                name=job.request.root_path.name or ".",
                total_bytes=0,
                duplicate_bytes=0,
                identical_groups=0,
                near_groups=0,
                children=[],
            )
        return TreemapResponse(
            scan_id=scan_id,
            generated_at=datetime.now(timezone.utc),
            root_path=job.request.root_path,
            tree=job.treemap,
        )

    def get_group_diff(
        self,
        scan_id: str,
        group_id: str,
        left_relative: str,
        right_relative: str,
    ) -> GroupDiff:
        job = self.get_job(scan_id)
        if job.status != ScanStatus.COMPLETED or not job.result:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Scan is not complete")

        target_record: Optional[GroupRecord] = None
        for records in job.groups.values():
            for record in records:
                if record.group_id == group_id:
                    target_record = record
                    break
            if target_record:
                break
        if not target_record:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")

        left_member = next((member for member in target_record.members if member.relative_path == left_relative), None)
        right_member = next((member for member in target_record.members if member.relative_path == right_relative), None)
        if not left_member or not right_member:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Members not found in group")

        fingerprints = job.result.fingerprints
        if left_member.relative_path not in fingerprints or right_member.relative_path not in fingerprints:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fingerprint missing for members")

        diff = compute_fingerprint_diff(
            fingerprints[left_member.relative_path],
            fingerprints[right_member.relative_path],
        )

        return GroupDiff(
            left=left_member,
            right=right_member,
            only_left=diff.only_left,
            only_right=diff.only_right,
            mismatched=diff.mismatched,
        )

    def get_group_contents(self, scan_id: str, group_id: str) -> GroupContents:
        job = self.get_job(scan_id)
        if job.status != ScanStatus.COMPLETED or not job.result:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Scan is not complete")

        group_record: Optional[GroupRecord] = None
        for groups in job.groups.values():
            for record in groups:
                if record.group_id == group_id:
                    group_record = record
                    break
            if group_record:
                break
        if not group_record:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")

        fingerprints = job.result.fingerprints
        if not fingerprints:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Missing fingerprint data")

        def build_contents(member: GroupRecord["members"][0]) -> MemberContents:
            fp = fingerprints.get(member.relative_path)
            if not fp:
                entries: List[DiffEntry] = []
            else:
                entries = [
                    DiffEntry(path=_identity_to_path(identity), bytes=bytes_size)
                    for identity, bytes_size in fp.file_weights.items()
                ]
            entries.sort(key=lambda entry: entry.path)
            folder_entries = [FolderEntry(path=entry.path, bytes=entry.bytes) for entry in entries]
            return MemberContents(relative_path=member.relative_path, entries=folder_entries)

        canonical_contents = build_contents(group_record.members[0])
        duplicate_contents = [build_contents(member) for member in group_record.members[1:]]

        return GroupContents(
            group_id=group_id,
            canonical=canonical_contents,
            duplicates=duplicate_contents,
        )

    def create_deletion_plan(self, scan_id: str, payload: DeletionPlanPayload) -> DeletionPlan:
        job = self.get_job(scan_id)
        if not job.request.deletion_enabled:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Deletion is disabled")

        root = job.request.root_path
        plan_paths: List[str] = []
        total_bytes = 0
        for rel_path in payload.paths:
            abs_path = (root / rel_path).resolve()
            if root not in abs_path.parents and abs_path != root:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Path escapes root: {rel_path}")
            if not abs_path.exists():
                continue
            size = _compute_path_size(abs_path)
            total_bytes += size
            plan_paths.append(abs_path.relative_to(root).as_posix())

        plan_id = uuid.uuid4().hex[:12]
        token = uuid.uuid4().hex
        quarant_root = root / ".folderdupe_quarantine" / datetime.now(timezone.utc).strftime("%Y%m%d")
        plan = DeletionPlan(
            plan_id=plan_id,
            token=token,
            reclaimable_bytes=total_bytes,
            queue=plan_paths,
            root=root,
            quarantine_root=quarant_root,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        with self._lock:
            self._plans[plan_id] = plan
        return plan

    def execute_plan(self, plan_id: str, token: str) -> DeletionResult:
        with self._lock:
            if plan_id not in self._plans:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plan not found")
            plan = self._plans[plan_id]
        if token != plan.token:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid confirmation token")
        if datetime.now(timezone.utc) > plan.expires_at:
            raise HTTPException(status_code=status.HTTP_410_GONE, detail="Plan expired")

        moved = 0
        bytes_moved = 0
        plan.quarantine_root.mkdir(parents=True, exist_ok=True)
        root = plan.root
        for rel_path in plan.queue:
            source = (root / rel_path).resolve()
            if not source.exists():
                continue
            if root not in source.parents and source != root:
                continue
            target = plan.quarantine_root / rel_path
            if target.exists():
                target = plan.quarantine_root / f"{target.name}_{uuid.uuid4().hex[:6]}"
            try:
                bytes_moved += _move_to_quarantine(source, target)
                moved += 1
            except OSError as exc:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to move {source}: {exc}",
                )

        with self._lock:
            self._plans.pop(plan_id, None)

        return DeletionResult(
            plan_id=plan_id,
            moved_count=moved,
            bytes_moved=bytes_moved,
            quarantine_root=plan.quarantine_root,
            root=plan.root,
        )

    def export(
        self,
        scan_id: str,
        fmt: str,
        filters: Optional[ExportFilters] = None,
    ) -> bytes:
        job = self.get_job(scan_id)
        if job.status != ScanStatus.COMPLETED:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Scan is not complete")
        filters = filters or ExportFilters()
        header = ExportHeader(
            generated_at=datetime.now(timezone.utc),
            root=job.request.root_path,
            file_equality=job.request.file_equality,
            min_similarity=job.request.similarity_threshold,
            structure_policy=job.request.structure_policy,
            filters=filters,
        )
        groups = self.get_groups(scan_id)
        groups = _apply_filters(groups, filters)
        if fmt == "json":
            payload = {
                "header": json.loads(header.json()),
                "groups": [json.loads(group.json()) for group in groups],
            }
            return json.dumps(payload, indent=2).encode("utf-8")
        if fmt == "csv":
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(
                [
                    "group_id",
                    "label",
                    "canonical_path",
                    "member_path",
                    "total_bytes",
                    "file_count",
                    "unstable",
                ]
            )
            for group in groups:
                for member in group.members:
                    writer.writerow(
                        [
                            group.group_id,
                            group.label.value,
                            str(group.canonical_path),
                            str(member.path),
                            member.total_bytes,
                            member.file_count,
                            member.unstable,
                        ]
                    )
            return output.getvalue().encode("utf-8")
        if fmt == "md":
            lines = [
                f"# Duplicate Report — {header.generated_at.isoformat()}",
                "",
                f"- Root: `{header.root}`",
                f"- File equality: `{header.file_equality.value}`",
                f"- Min similarity: `{header.min_similarity:.2f}`",
                "",
            ]
            for group in groups:
                lines.append(f"## {group.group_id} — {group.label.value}")
                lines.append(f"- Canonical: `{group.canonical_path}`")
                lines.append("")
                for member in group.members:
                    lines.append(
                        f"  - `{member.path}` — bytes: {member.total_bytes:,}, files: {member.file_count}"
                    )
                lines.append("")
            return "\n".join(lines).encode("utf-8")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown export format")

    def _update_active_metric(self) -> None:
        if not self._metrics:
            return
        with self._lock:
            active = sum(1 for job in self._jobs.values() if job.status == ScanStatus.RUNNING)
        self._metrics.set_active_scans(active)

    def _record_metrics(self, job: ScanJob) -> None:
        if not self._metrics:
            return
        timings = [job.phase_timings[name] for name in job.phase_sequence if name in job.phase_timings]
        self._metrics.record_scan(job.stats.get("bytes_scanned", 0), timings)

    def get_metrics(self, scan_id: str) -> ScanMetrics:
        job = self.get_job(scan_id)
        timings = [job.phase_timings[name] for name in job.phase_sequence]
        return ScanMetrics(
            scan_id=job.scan_id,
            root_path=job.request.root_path,
            started_at=job.started_at,
            completed_at=job.completed_at,
            worker_count=job.stats.get("workers", 0),
            bytes_scanned=job.stats.get("bytes_scanned", 0),
            phase_timings=timings,
            resource_samples=job.resource_samples,
        )

    def _run_scan(self, job: ScanJob) -> None:
        job.status = ScanStatus.RUNNING
        self._update_active_metric()
        job.set_phase("walking")
        try:
            job.meta["phase"] = "walking"
            scanner = FolderScanner(
                job.request,
                cache=self.file_cache,
                stats_sink=job.stats,
                meta_sink=job.meta,
                phase_callback=job.handle_phase_transition,
            )
            result = scanner.scan()
            job.meta["phase"] = "grouping"
            job.set_phase("grouping")
            similarity_groups = compute_similarity_groups(
                result.fingerprints,
                job.request.similarity_threshold,
                stats=job.stats,
                meta=job.meta,
            )

            records_by_label: Dict[FolderLabel, List[GroupRecord]] = {label: [] for label in FolderLabel}
            combined_records: List[Tuple[FolderLabel, GroupRecord]] = []

            for group in similarity_groups:
                group_id, members, pairs, divergences = group_to_record(
                    group,
                    FolderLabel.NEAR_DUPLICATE if group.max_similarity < 1.0 else FolderLabel.IDENTICAL,
                    result.fingerprints,
                )
                label = FolderLabel.NEAR_DUPLICATE if group.max_similarity < 1.0 else FolderLabel.IDENTICAL
                record = GroupRecord(
                    group_id=group_id,
                    label=label,
                    canonical_path=members[0].path,
                    members=members,
                    pairwise_similarity=pairs,
                    divergences=divergences,
                    suppressed_descendants=False,
                )
                records_by_label[label].append(record)
                combined_records.append((label, record))

            filtered_records = _suppress_descendant_groups_all(combined_records)
            for label in FolderLabel:
                job.groups[label] = []
            for label, record in filtered_records:
                job.groups[label].append(record)

            if job.request.include_matrix:
                job.matrix_entries = build_similarity_matrix(
                    filtered_records,
                    max_entries=self.config.matrix_max_entries,
                    min_reclaim_bytes=self.config.matrix_min_reclaim_bytes,
                    include_identical=self.config.matrix_include_identical,
                )
            else:
                job.matrix_entries = []

            if job.request.include_treemap:
                root_label = job.request.root_path.name or job.request.root_path.as_posix()
                root_fingerprint = result.fingerprints.get(".")
                root_bytes = root_fingerprint.folder.total_bytes if root_fingerprint else 0
                job.treemap = build_treemap(filtered_records, root_label=root_label, root_bytes=root_bytes)
            else:
                job.treemap = None

            job.result = result
            job.warnings = result.warnings
            job.stats = result.stats
            job.status = ScanStatus.COMPLETED
            job.completed_at = datetime.now(timezone.utc)
            job.finish_phase()
            self._record_metrics(job)
        except Exception as exc:  # pylint: disable=broad-except
            # Treat unexpected errors as warnings when we already
            # have a partial result, instead of failing the entire
            # scan. This keeps completed scans usable even if
            # secondary steps (e.g., analytics) raise.
            job.completed_at = datetime.now(timezone.utc)
            if job.result is not None:
                job.status = ScanStatus.COMPLETED
            else:
                job.status = ScanStatus.FAILED
            job.error = str(exc)
            job.warnings.append(
                WarningRecord(
                    path=job.request.root_path,
                    type=WarningType.IO_ERROR,
                    message=str(exc),
                )
            )
        finally:
            job.finish_phase()
            self._update_active_metric()


class ThreadPoolExecutorWithStop:
    def __init__(self, max_workers: int) -> None:
        from concurrent.futures import ThreadPoolExecutor

        self._executor = ThreadPoolExecutor(max_workers=max_workers)

    def submit(self, fn, *args, **kwargs):
        return self._executor.submit(fn, *args, **kwargs)

    def shutdown(self, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait)


def _move_to_quarantine(source: Path, target: Path) -> int:
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.move(str(source), str(target))
        return sum(f.stat().st_size for f in target.rglob("*") if f.is_file())
    shutil.move(str(source), str(target))
    return target.stat().st_size


def _compute_path_size(path: Path) -> int:
    if path.is_dir():
        return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    if path.is_file():
        return path.stat().st_size
    return 0


def _apply_filters(groups: List[GroupRecord], filters: ExportFilters) -> List[GroupRecord]:
    if not filters.include and not filters.exclude:
        return groups

    def match(path_str: str, patterns: List[str]) -> bool:
        return any(fnmatch.fnmatch(path_str, pattern) for pattern in patterns)

    filtered: List[GroupRecord] = []
    for group in groups:
        canonical = str(group.canonical_path)
        if filters.include and not match(canonical, filters.include):
            continue
        if filters.exclude and match(canonical, filters.exclude):
            continue
        filtered.append(group)
    return filtered


def _suppress_descendant_groups_all(
    records: List[Tuple[FolderLabel, GroupRecord]]
) -> List[Tuple[FolderLabel, GroupRecord]]:
    if not records:
        return []

    sorted_records = sorted(records, key=lambda item: _record_min_depth(item[1]))
    kept: List[Tuple[FolderLabel, GroupRecord]] = []
    ancestor_sets: List[Set[Path]] = []

    for label, record in sorted_records:
        member_paths = [member.path if isinstance(member.path, Path) else Path(member.path) for member in record.members]
        if any(_all_members_descend(member_paths, ancestors) for ancestors in ancestor_sets):
            continue
        kept.append((label, record))
        ancestor_sets.append(
            {member.path if isinstance(member.path, Path) else Path(member.path) for member in record.members}
        )

    kept.sort(key=lambda item: (_record_min_depth(item[1]), str(item[1].canonical_path)))
    return kept


def _all_members_descend(members: List[Path], ancestors: set[Path]) -> bool:
    for member in members:
        if not any(_is_descendant_path(member, ancestor) for ancestor in ancestors):
            return False
    return True


def _is_descendant_path(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _record_min_depth(record: GroupRecord) -> int:
    depths = []
    for member in record.members:
        rel = member.relative_path or "."
        rel_path = Path(rel)
        depth = 0 if rel_path == Path(".") else len(rel_path.parts)
        depths.append(depth)
    return min(depths) if depths else 0
