from __future__ import annotations

import fnmatch
import hashlib
import os
import threading
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

from .cache import FileHashCache, FileCacheKey
from .domain import FolderInfo, GroupInfo
from .models import (
    DirectoryFingerprint,
    DivergenceRecord,
    DiffEntry,
    FileEqualityMode,
    FileRecord,
    FolderLabel,
    GroupDiff,
    MismatchEntry,
    PairwiseSimilarity,
    ScanRequest,
    StructurePolicy,
    WarningRecord,
    WarningType,
)


HASH_CHUNK_SIZE = 4 * 1024 * 1024


def _to_folder_record(info: FolderInfo) -> FolderRecord:
    return FolderRecord(
        path=info.path,
        relative_path=info.relative_path,
        total_bytes=info.total_bytes,
        file_count=info.file_count,
        unstable=info.unstable,
    )


@dataclass
class ScanResult:
    folders: Dict[str, FolderInfo]
    fingerprints: Dict[str, DirectoryFingerprint]
    warnings: List[WarningRecord]
    stats: Dict[str, int]


class FolderScanner:
    def __init__(
        self,
        request: ScanRequest,
        cache: Optional[FileHashCache] = None,
        stats_sink: Optional[Dict[str, int]] = None,
        meta_sink: Optional[Dict[str, str]] = None,
        phase_callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.request = request
        self.cache = cache
        self._stats_sink = stats_sink
        self._meta_sink = meta_sink
        self._phase_callback = phase_callback
        self._warnings: List[WarningRecord] = []
        self._stats: Dict[str, int] = defaultdict(int)
        self._seen_inodes: Set[Tuple[int, int]] = set()
        self._lock = threading.RLock()
        self._set_stat("files_scanned", 0)
        self._set_stat("folders_scanned", 0)
        self._set_stat("folders_discovered", 1)
        self._set_stat("bytes_scanned", 0)

    def scan(self) -> ScanResult:
        root = self.request.root_path
        folders: Dict[str, FolderInfo] = {}
        fingerprints: Dict[str, DirectoryFingerprint] = {}

        if not root.is_dir():
            raise FileNotFoundError(f"Root path {root} is not a directory")

        max_workers = self.request.concurrency or min(32, (os.cpu_count() or 4) * 2)
        self._set_stat("workers", max_workers)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for dirpath, dirnames, filenames in os.walk(root):
                current = Path(dirpath)
                if getattr(self, "_meta_sink", None) is not None:
                    self._meta_sink["last_path"] = str(current)
                rel_dir = current.relative_to(root)
                if self._is_excluded(rel_dir):
                    dirnames[:] = []
                    continue

                filtered_dirnames: List[str] = []
                for dirname in dirnames:
                    rel_child = rel_dir / dirname
                    if self._is_excluded(rel_child):
                        continue
                    filtered_dirnames.append(dirname)
                dirnames[:] = filtered_dirnames
                if filtered_dirnames:
                    self._increment_stat("folders_discovered", len(filtered_dirnames))

                files: List[FileRecord] = []
                total_size = 0
                unstable = False
                futures = []
                for filename in filenames:
                    if getattr(self, "_meta_sink", None) is not None:
                        self._meta_sink["last_path"] = str(current / filename)
                    futures.append(executor.submit(self._process_file, current, filename, rel_dir))
                for future in futures:
                    record, file_unstable = future.result()
                    if file_unstable:
                        unstable = True
                    if record:
                        files.append(record)
                        total_size += record.size

                folder_record = FolderInfo(
                    path=str(current),
                    relative_path=rel_dir.as_posix() if rel_dir != Path(".") else ".",
                    total_bytes=total_size,
                    file_count=len(files),
                    unstable=unstable,
                )
                folder_key = folder_record.relative_path
                folders[folder_key] = folder_record
                fingerprint = self._build_fingerprint(folder_record, files)
                fingerprints[folder_key] = fingerprint
                self._set_stat("folders_scanned", len(folders))

        self._stats["folders_scanned"] = len(folders)
        if getattr(self, "_meta_sink", None) is not None:
            self._meta_sink["phase"] = "aggregating"
        if self._phase_callback:
            self._phase_callback("aggregating")
        fingerprints = aggregate_fingerprints(fingerprints, self._stats, self._meta_sink)
        return ScanResult(
            folders=folders,
            fingerprints=fingerprints,
            warnings=self._warnings,
            stats=dict(self._stats),
        )

    def _is_excluded(self, rel: Path) -> bool:
        rel_posix = rel.as_posix()
        for pattern in self.request.exclude:
            if fnmatch.fnmatch(rel_posix, pattern):
                return True
        return False

    def _is_included(self, rel: str) -> bool:
        if not self.request.include:
            return True
        return any(fnmatch.fnmatch(rel, pattern) for pattern in self.request.include)

    def _process_file(self, current: Path, filename: str, rel_dir: Path) -> Tuple[Optional[FileRecord], bool]:
        file_path = current / filename
        rel_path = (rel_dir / filename).as_posix()
        if self._is_excluded(Path(rel_path)):
            return None, False
        if not self._is_included(rel_path):
            return None, False
        try:
            stat = file_path.stat()
        except PermissionError:
            self._add_warning(
                WarningRecord(
                    path=file_path,
                    type=WarningType.PERMISSION,
                    message="Permission denied",
                )
            )
            return None, False
        except OSError as exc:
            self._add_warning(
                WarningRecord(
                    path=file_path,
                    type=WarningType.IO_ERROR,
                    message=f"I/O error: {exc}",
                )
            )
            return None, False

        if not file_path.is_file() or os.path.islink(file_path):
            return None, False

        inode_key = (stat.st_dev, stat.st_ino)
        with self._lock:
            if inode_key in self._seen_inodes:
                return None, False
            self._seen_inodes.add(inode_key)

        record = self._build_file_record(file_path, rel_path, stat)
        if record is None:
            return None, True

        self._increment_stat("files_scanned")
        self._increment_stat("bytes_scanned", record.size)
        return record, False

    def _add_warning(self, warning: WarningRecord) -> None:
        with self._lock:
            self._warnings.append(warning)

    def _increment_stat(self, key: str, amount: int = 1) -> None:
        with self._lock:
            self._stats[key] += amount
            if self._stats_sink is not None:
                self._stats_sink[key] = self._stats[key]

    def _set_stat(self, key: str, value: int) -> None:
        with self._lock:
            self._stats[key] = value
            if self._stats_sink is not None:
                self._stats_sink[key] = value

    def _build_file_record(self, path: Path, rel_path: str, stat: os.stat_result) -> Optional[FileRecord]:
        mtime = stat.st_mtime
        size = stat.st_size
        sha256_hash: Optional[str] = None

        if self.request.file_equality == FileEqualityMode.SHA256:
            cached = self._lookup_cache(stat, size, mtime)
            if cached:
                sha256_hash = cached
            else:
                sha256_hash, stable = self._hash_file(path, size, mtime)
                if not stable:
                    return None
                if sha256_hash and self.cache:
                    self.cache.set(self._cache_key(stat, size, mtime), sha256_hash)

        rel_display = rel_path
        if self.request.force_case_insensitive:
            rel_display = rel_display.lower()

        return FileRecord(
            path=path,
            relative_path=rel_display,
            size=size,
            mtime=mtime,
            sha256=sha256_hash,
        )

    def _cache_key(self, stat: os.stat_result, size: int, mtime: float) -> FileCacheKey:
        return (int(stat.st_dev), int(stat.st_ino), int(size), float(mtime))

    def _lookup_cache(self, stat: os.stat_result, size: int, mtime: float) -> Optional[str]:
        if not self.cache:
            return None
        return self.cache.get(self._cache_key(stat, size, mtime))

    def _hash_file(self, path: Path, expected_size: int, expected_mtime: float) -> Tuple[Optional[str], bool]:
        """Return (sha256, stable). Performs drift detection."""

        def _read() -> Tuple[Optional[str], bool]:
            h = hashlib.sha256()
            read_bytes = 0
            try:
                with path.open("rb") as f:
                    while True:
                        chunk = f.read(HASH_CHUNK_SIZE)
                        if not chunk:
                            break
                        h.update(chunk)
                        read_bytes += len(chunk)
            except PermissionError:
                self._add_warning(
                    WarningRecord(
                        path=path,
                        type=WarningType.PERMISSION,
                        message="Permission denied while hashing",
                    )
                )
                return None, False
            except OSError as exc:
                self._add_warning(
                    WarningRecord(
                        path=path,
                        type=WarningType.IO_ERROR,
                        message=f"I/O error while hashing: {exc}",
                    )
                )
                return None, False
            if read_bytes != expected_size:
                return None, False
            return h.hexdigest(), True

        digest, stable = _read()
        if not stable:
            stat_after = path.stat()
            if stat_after.st_size != expected_size or stat_after.st_mtime != expected_mtime:
                # Drift detected, retry once
                digest, stable = _read()
                if not stable:
                    self._add_warning(
                        WarningRecord(
                            path=path,
                            type=WarningType.UNSTABLE,
                            message="File changed during hashing twice; skipping",
                        )
                    )
                    return None, False
        return digest, True

    def _build_fingerprint(self, folder: FolderInfo, files: List[FileRecord]) -> DirectoryFingerprint:
        weights: Dict[str, int] = defaultdict(int)
        folder_prefix = Path(folder.relative_path) if folder.relative_path != "." else None

        for record in files:
            record_path = Path(record.relative_path)
            if folder_prefix:
                try:
                    relative_path = record_path.relative_to(folder_prefix)
                except ValueError:
                    relative_path = Path(record_path.name)
            else:
                relative_path = record_path
            identity = self._file_identity(relative_path, record)
            weights[identity] += record.size
        return DirectoryFingerprint(folder=folder, file_weights=dict(weights))

    def _file_identity(self, relative_path: Path, record: FileRecord) -> str:
        if self.request.structure_policy == StructurePolicy.BAG_OF_FILES:
            base = relative_path.name
        else:
            base = relative_path.as_posix()
        if self.request.file_equality == FileEqualityMode.SHA256:
            return f"{base}#{record.sha256}"
        return f"{base}:{record.size}"

def aggregate_fingerprints(
    fingerprints: Dict[str, DirectoryFingerprint],
    stats: Optional[Dict[str, int]] = None,
    meta: Optional[Dict[str, str]] = None,
) -> Dict[str, DirectoryFingerprint]:
    aggregated: Dict[str, DirectoryFingerprint] = {}
    children: Dict[str, List[str]] = defaultdict(list)
    for key in fingerprints:
        parent = str(Path(key).parent) if key != "." else None
        if parent:
            children[parent].append(key)

    total = len(fingerprints)
    if stats is not None:
        stats["total_folders"] = total
        stats["folders_aggregated"] = 0

    for index, key in enumerate(sorted(fingerprints.keys(), key=lambda value: len(Path(value).parts), reverse=True), start=1):
        fingerprint = fingerprints[key]
        combined = dict(fingerprint.file_weights)
        for child_key in children.get(key, []):
            child_fp = aggregated.get(child_key)
            if not child_fp:
                continue
            prefix_path = Path(child_key).relative_to(Path(key)) if key != "." else Path(child_key)
            for identity, weight in child_fp.file_weights.items():
                prefixed_identity = _prefix_identity(prefix_path, identity)
                combined[prefixed_identity] = combined.get(prefixed_identity, 0) + weight
        aggregated_fp = DirectoryFingerprint(folder=fingerprint.folder, file_weights=combined)
        total_bytes = sum(combined.values())
        file_count = len(combined)
        fingerprint.folder.total_bytes = total_bytes
        fingerprint.folder.file_count = file_count
        aggregated[key] = aggregated_fp
        if stats is not None:
            stats["folders_aggregated"] = index
        if meta is not None:
            meta["last_path"] = fingerprint.folder.path
    return aggregated


def compute_fingerprint_diff(
    left: DirectoryFingerprint,
    right: DirectoryFingerprint,
) -> GroupDiff:
    left_map = _identity_map(left.file_weights)
    right_map = _identity_map(right.file_weights)

    only_left: List[DiffEntry] = []
    only_right: List[DiffEntry] = []
    mismatched: List[MismatchEntry] = []

    for path, bytes_left in left_map.items():
        if path not in right_map:
            only_left.append(DiffEntry(path=path, bytes=bytes_left))
        else:
            bytes_right = right_map[path]
            if bytes_left != bytes_right:
                mismatched.append(
                    MismatchEntry(path=path, left_bytes=bytes_left, right_bytes=bytes_right)
                )

    for path, bytes_right in right_map.items():
        if path not in left_map:
            only_right.append(DiffEntry(path=path, bytes=bytes_right))

    only_left.sort(key=lambda entry: entry.path)
    only_right.sort(key=lambda entry: entry.path)
    mismatched.sort(key=lambda entry: entry.path)

    return GroupDiff(
        left=_to_folder_record(left.folder),
        right=_to_folder_record(right.folder),
        only_left=only_left,
        only_right=only_right,
        mismatched=mismatched,
    )


def _identity_map(weights: Dict[str, int]) -> Dict[str, int]:
    mapping: Dict[str, int] = {}
    for identity, bytes_size in weights.items():
        path = _identity_to_path(identity)
        mapping[path] = mapping.get(path, 0) + bytes_size
    return mapping


def _identity_to_path(identity: str) -> str:
    if "#" in identity:
        return identity.split("#", 1)[0]
    if ":" in identity:
        return identity.rsplit(":", 1)[0]
    return identity


def compute_similarity_groups(
    fingerprints: Dict[str, DirectoryFingerprint],
    threshold: float,
    stats: Optional[Dict[str, int]] = None,
    meta: Optional[Dict[str, str]] = None,
) -> List["SimilarityGroup"]:
    folders = list(fingerprints.values())
    buckets: Dict[int, List[DirectoryFingerprint]] = defaultdict(list)
    for fingerprint in folders:
        bucket_key = round(fingerprint.folder.total_bytes / (10 * 1024 * 1024))
        buckets[bucket_key].append(fingerprint)

    groups: List[SimilarityGroup] = []

    total_pairs = 0
    for bucket_items in buckets.values():
        n = len(bucket_items)
        if n > 1:
            total_pairs += n * (n - 1) // 2
    if stats is not None:
        stats["similarity_pairs_total"] = total_pairs
        stats["similarity_pairs_processed"] = 0

    for bucket_items in buckets.values():
        for i, a in enumerate(bucket_items):
            for b in bucket_items[i + 1 :]:
                if stats is not None:
                    stats["similarity_pairs_processed"] += 1
                if meta is not None:
                    meta["last_path"] = str(a.folder.path)
                if _is_ancestor_descendant_pair(a.folder.relative_path, b.folder.relative_path):
                    continue
                similarity = weighted_jaccard(a.file_weights, b.file_weights)
                if similarity >= threshold:
                    groups.append(
                        SimilarityGroup(
                            members=[a.folder, b.folder],
                            similarity_pairs=[PairwiseSimilarity(a=0, b=1, similarity=similarity)],
                        )
                    )
    return merge_groups(groups, threshold)


def weighted_jaccard(a: Dict[str, int], b: Dict[str, int]) -> float:
    """Compute weighted Jaccard similarity without allocating large helper sets.

    This implementation iterates over the smaller mapping first and uses
    direct dictionary lookups to accumulate the intersection and union,
    avoiding the temporary ``set(a) | set(b)`` previously used. That
    significantly reduces peak RAM during large grouping runs because we
    no longer materialize full key unions for every pairwise comparison.
    """
    if not a and not b:
        return 0.0

    # Always iterate the smaller mapping first to minimise lookups.
    if len(a) <= len(b):
        smaller, larger = a, b
    else:
        smaller, larger = b, a

    intersection = 0
    union = 0

    for key, wa in smaller.items():
        wb = larger.get(key)
        if wb is None:
            union += wa
        else:
            if wa <= wb:
                intersection += wa
                union += wb
            else:
                intersection += wb
                union += wa

    for key, wb in larger.items():
        if key not in smaller:
            union += wb

    if union == 0:
        return 0.0
    return intersection / union


class SimilarityGroup:
    def __init__(
        self,
        members: List[FolderInfo],
        similarity_pairs: List[PairwiseSimilarity],
    ) -> None:
        self.members = members
        self.similarity_pairs = similarity_pairs

    @property
    def max_similarity(self) -> float:
        return max((pair.similarity for pair in self.similarity_pairs), default=0.0)


def merge_groups(groups: List[SimilarityGroup], threshold: float) -> List[SimilarityGroup]:
    """Merge overlapping groups into clusters."""
    if not groups:
        return []
    adjacency: Dict[str, Set[str]] = defaultdict(set)
    folder_lookup: Dict[str, FolderInfo] = {}
    pairs: Dict[Tuple[str, str], float] = {}

    for group in groups:
        members = group.members
        for member in members:
            folder_lookup[member.relative_path] = member
        for pair in group.similarity_pairs:
            a = members[pair.a].relative_path
            b = members[pair.b].relative_path
            adjacency[a].add(b)
            adjacency[b].add(a)
            key = tuple(sorted((a, b)))
            pairs[key] = pair.similarity

    visited: Set[str] = set()
    merged: List[SimilarityGroup] = []

    for node in adjacency:
        if node in visited:
            continue
        stack = [node]
        cluster: List[str] = []
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            cluster.append(current)
            stack.extend(adjacency[current] - visited)

        member_records = [folder_lookup[name] for name in cluster]
        similarity_pairs: List[PairwiseSimilarity] = []
        for i, a in enumerate(cluster):
            for j, b in enumerate(cluster):
                if j <= i:
                    continue
                key = tuple(sorted((a, b)))
                similarity = pairs.get(key, 0.0)
                if similarity > 0:
                    similarity_pairs.append(PairwiseSimilarity(a=i, b=j, similarity=similarity))
        merged.append(SimilarityGroup(member_records, similarity_pairs))

    return merged


def classify_groups(
    groups: Iterable[SimilarityGroup],
    threshold: float,
    fingerprints: Dict[str, DirectoryFingerprint],
) -> Dict[FolderLabel, List[Tuple[SimilarityGroup, float]]]:
    classified: Dict[FolderLabel, List[Tuple[SimilarityGroup, float]]] = defaultdict(list)
    for group in groups:

        max_similarity = group.max_similarity
        if max_similarity >= 1.0 - 1e-9:
            label = FolderLabel.IDENTICAL
        elif max_similarity >= threshold:
            label = FolderLabel.NEAR_DUPLICATE
        else:
            label = FolderLabel.PARTIAL_OVERLAP
        if label == FolderLabel.IDENTICAL:
            base_bytes = group.members[0].total_bytes
            base_count = group.members[0].file_count
            for member in group.members[1:]:
                if member.total_bytes != base_bytes or member.file_count != base_count:
                    label = FolderLabel.NEAR_DUPLICATE
                    break
        classified[label].append((group, max_similarity))
    return classified


def group_to_record(
    group: SimilarityGroup,
    label: FolderLabel,
    fingerprints: Dict[str, DirectoryFingerprint],
) -> GroupInfo:
    members = sorted(group.members, key=lambda f: (len(f.path), f.path))
    canonical = members[0]
    group_uuid = uuid.uuid5(uuid.NAMESPACE_URL, canonical.path)
    group_id = f"g_{group_uuid.hex[:8]}"
    divergences: List[DivergenceRecord] = []

    if label != FolderLabel.IDENTICAL and len(members) >= 2:
        base = fingerprints[members[0].relative_path]
        compared = fingerprints[members[1].relative_path]
        divergences = compute_divergences(base.file_weights, compared.file_weights)

    return GroupInfo(
        group_id=group_id,
        label=label,
        canonical_path=canonical.path,
        members=members,
        pairwise_similarity=group.similarity_pairs,
        divergences=divergences,
        suppressed_descendants=False,
    )


def compute_divergences(a: Dict[str, int], b: Dict[str, int], top_k: int = 5) -> List[DivergenceRecord]:
    deltas: List[Tuple[str, int]] = []
    keys = set(a.keys()) | set(b.keys())
    for key in keys:
        delta = abs(a.get(key, 0) - b.get(key, 0))
        if delta > 0:
            deltas.append((key, delta))
    deltas.sort(key=lambda item: item[1], reverse=True)
    records: List[DivergenceRecord] = []
    for name, delta in deltas[:top_k]:
        if ":" in name:
            path = name.split(":", 1)[0]
        elif "#" in name:
            path = name.split("#", 1)[0]
        else:
            path = name
        records.append(DivergenceRecord(path_a=path, path_b=path, delta_bytes=delta))
    return records


def _is_ancestor_descendant_pair(path_a: str, path_b: str) -> bool:
    if path_a == path_b:
        return False
    if path_a == "." or path_b == ".":
        return True
    if path_a.endswith("/"):
        path_a = path_a.rstrip("/")
    if path_b.endswith("/"):
        path_b = path_b.rstrip("/")
    return path_b.startswith(f"{path_a}/") or path_a.startswith(f"{path_b}/")


def _prefix_identity(prefix: Path, identity: str) -> str:
    if not prefix or str(prefix) in (".", ""):
        return identity
    prefix_str = prefix.as_posix()
    if not identity:
        return prefix_str
    if "#" in identity:
        base, rest = identity.split("#", 1)
        base = base.strip("/")
        combined_base = f"{prefix_str}/{base}" if base else prefix_str
        return f"{combined_base}#{rest}"
    if ":" in identity:
        base, rest = identity.split(":", 1)
        base = base.strip("/")
        combined_base = f"{prefix_str}/{base}" if base else prefix_str
        return f"{combined_base}:{rest}"
    return f"{prefix_str}/{identity}"
