from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

from app.analytics import build_similarity_matrix, build_treemap
from app.domain import GroupInfo
from app.models import FolderLabel, ScanRequest, TreemapNode
from app.scanner import FolderScanner, classify_groups, compute_similarity_groups, group_to_record
from app.store import _suppress_descendant_groups_all

from .utils import write_file


def _build_case(tmp_path: Path) -> Tuple[List[Tuple[FolderLabel, GroupInfo]], int, str]:
    root = tmp_path / "photos"
    write_file(root / "albumA" / "set1" / "shot.raw", b"A" * 1024)
    write_file(root / "albumA" / "set1" / "notes.txt", b"meta")
    write_file(root / "albumB" / "set1" / "shot.raw", b"A" * 1024)
    write_file(root / "albumB" / "set1" / "notes.txt", b"meta")
    write_file(root / "albumB" / "extras" / "shot.raw", b"extra")

    request = ScanRequest(root_path=root)
    scanner = FolderScanner(request)
    result = scanner.scan()
    groups = compute_similarity_groups(result.fingerprints, request.similarity_threshold)
    classified = classify_groups(groups, request.similarity_threshold, result.fingerprints)

    records: List[Tuple[FolderLabel, GroupInfo]] = []
    for label, label_groups in classified.items():
        for group, _ in label_groups:
            info = group_to_record(group, label, result.fingerprints)
            records.append((label, info))

    filtered = _suppress_descendant_groups_all(records)
    root_bytes = result.fingerprints["."].folder.total_bytes if "." in result.fingerprints else 0
    return filtered, root_bytes, root.name


def test_similarity_matrix_entries_sorted(tmp_path: Path) -> None:
    records, _, _ = _build_case(tmp_path)
    entries = build_similarity_matrix(records)
    assert entries, "matrix should include adjacency rows"
    assert entries == sorted(entries, key=lambda item: (item.similarity, item.combined_bytes), reverse=True)
    assert all(entry.reclaimable_bytes <= entry.combined_bytes for entry in entries)


def test_treemap_rolls_up_duplicate_bytes(tmp_path: Path) -> None:
    records, root_bytes, root_label = _build_case(tmp_path)
    tree = build_treemap(records, root_label=root_label, root_bytes=root_bytes)
    assert tree.duplicate_bytes >= 0
    assert tree.children, "root should expose child folders"
    leaf = _find_node(tree, "albumA")
    assert leaf is not None
    if leaf.children:
        assert leaf.duplicate_bytes >= leaf.children[0].duplicate_bytes
    assert leaf.near_groups >= 0
    assert tree.duplicate_bytes >= leaf.duplicate_bytes


def _find_node(node: TreemapNode, target: str) -> TreemapNode | None:
    if node.path.endswith(target):
        return node
    for child in node.children:
        match = _find_node(child, target)
        if match:
            return match
    return None
