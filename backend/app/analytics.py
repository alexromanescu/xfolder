from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Tuple, Optional
import heapq

from .domain import GroupInfo
from .converters import folder_info_to_record
from .models import FolderLabel, SimilarityMatrixEntry, TreemapNode


def build_similarity_matrix(
    records: Iterable[Tuple[FolderLabel, GroupInfo]],
    *,
    max_entries: Optional[int] = None,
    min_reclaim_bytes: int = 0,
    include_identical: bool = True,
) -> List[SimilarityMatrixEntry]:
    """Flatten similarity groups into adjacency entries sorted by similarity."""
    record_list = list(records)
    if not record_list:
        return []

    worker_cap = min(32, (os.cpu_count() or 4) * 2)
    worker_count = min(worker_cap, len(record_list))

    def _process(item: Tuple[FolderLabel, GroupInfo]) -> List[SimilarityMatrixEntry]:
        label, record = item
        members_info = record.members
        members = [folder_info_to_record(member) for member in members_info]
        if len(members) < 2 or not record.pairwise_similarity:
            return []
        chunk: List[SimilarityMatrixEntry] = []
        for pair in record.pairwise_similarity:
            if pair.a >= len(members) or pair.b >= len(members):
                continue
            left = members[pair.a]
            right = members[pair.b]
            combined_bytes = left.total_bytes + right.total_bytes
            reclaimable = min(left.total_bytes, right.total_bytes)
            if label == FolderLabel.NEAR_DUPLICATE:
                reclaimable = int(reclaimable * pair.similarity)
            chunk.append(
                SimilarityMatrixEntry(
                    group_id=record.group_id,
                    label=label,
                    left=left,
                    right=right,
                    similarity=round(pair.similarity, 4),
                    combined_bytes=combined_bytes,
                    reclaimable_bytes=reclaimable,
                )
            )
        return chunk

    # Use a (key, seq, entry) heap so ties on the key do not rely on
    # comparing SimilarityMatrixEntry instances directly (which is
    # unsupported under Pydantic v2).
    heap: List[Tuple[Tuple[float, int], int, SimilarityMatrixEntry]] = []
    entry_counter = 0

    def _maybe_add(entry: SimilarityMatrixEntry) -> None:
        nonlocal entry_counter
        if not include_identical and entry.label == FolderLabel.IDENTICAL:
            return
        if entry.reclaimable_bytes < min_reclaim_bytes:
            return
        if max_entries and max_entries > 0:
            key = (entry.similarity, entry.combined_bytes)
            if len(heap) < max_entries:
                heapq.heappush(heap, (key, entry_counter, entry))
                entry_counter += 1
            else:
                if key > heap[0][0]:
                    heapq.heapreplace(heap, (key, entry_counter, entry))
                    entry_counter += 1
        else:
            key = (entry.similarity, entry.combined_bytes)
            heap.append((key, entry_counter, entry))
            entry_counter += 1

    def _consume(items: Iterable[Tuple[FolderLabel, GroupInfo]]) -> None:
        if worker_count <= 1:
            for item in items:
                for entry in _process(item):
                    _maybe_add(entry)
        else:
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                for chunk in executor.map(_process, items):
                    for entry in chunk:
                        _maybe_add(entry)

    _consume(record_list)

    entries = [entry for _key, _seq, entry in heap]
    entries.sort(key=lambda item: (item.similarity, item.combined_bytes), reverse=True)
    return entries


@dataclass
class _TreemapBuilder:
    path: str
    name: str
    total_bytes: int = 0
    duplicate_bytes: int = 0
    identical_groups: int = 0
    near_groups: int = 0
    children: set[str] = field(default_factory=set)


def build_treemap(
    records: Iterable[Tuple[FolderLabel, GroupInfo]],
    *,
    root_label: str,
    root_bytes: int,
) -> TreemapNode:
    """Aggregate duplicate density per folder for treemap visualization."""
    builders: Dict[str, _TreemapBuilder] = {}

    def ensure_node(path: str) -> _TreemapBuilder:
        norm = path or "."
        if norm not in builders:
            name = root_label if norm == "." else (Path(norm).name or root_label)
            builders[norm] = _TreemapBuilder(path=norm, name=name)
        return builders[norm]

    root_builder = ensure_node(".")
    root_builder.total_bytes = root_bytes

    for label, record in records:
        if not record.members:
            continue
        canonical = record.members[0]
        path_key = canonical.relative_path or "."
        node = ensure_node(path_key)
        node.total_bytes = max(node.total_bytes, canonical.total_bytes)
        dup_bytes = sum(member.total_bytes for member in record.members[1:])
        node.duplicate_bytes += dup_bytes
        if label == FolderLabel.IDENTICAL:
            node.identical_groups += 1
        elif label == FolderLabel.NEAR_DUPLICATE:
            node.near_groups += 1

        for ancestor_key in _ancestor_chain(path_key):
            ancestor = ensure_node(ancestor_key)
            if ancestor_key != path_key:
                ancestor.duplicate_bytes += dup_bytes

    for path_key in list(builders.keys()):
        if path_key == ".":
            continue
        parent = str(Path(path_key).parent)
        if parent in ("", "."):
            parent = "."
        ensure_node(parent).children.add(path_key)

    def materialize(path: str) -> TreemapNode:
        builder = ensure_node(path)
        child_nodes = [materialize(child) for child in sorted(builder.children)]
        if builder.total_bytes == 0 and child_nodes:
            builder.total_bytes = sum(child.total_bytes for child in child_nodes)
        child_nodes.sort(key=lambda child: child.duplicate_bytes, reverse=True)
        return TreemapNode(
            path=path,
            name=builder.name,
            total_bytes=builder.total_bytes,
            duplicate_bytes=builder.duplicate_bytes,
            identical_groups=builder.identical_groups,
            near_groups=builder.near_groups,
            children=child_nodes,
        )

    return materialize(".")


def _ancestor_chain(path: str) -> List[str]:
    if path in (".", "", "/"):
        return ["."]
    normalized = Path(path).as_posix().strip("/")
    parts = normalized.split("/") if normalized else []
    ancestors = ["."]
    current = ""
    for part in parts:
        current = part if not current else f"{current}/{part}"
        ancestors.append(current)
    return ancestors
