from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

import pytest

from app.models import FolderLabel, FolderRecord, GroupRecord, ScanRequest
from app.scanner import (
    FolderScanner,
    classify_groups,
    compute_similarity_groups,
    group_to_record,
)
from app.store import _suppress_descendant_groups_all

from .utils import write_file


def build_nested_x_tree(tmp_path: Path) -> Path:
    root = tmp_path / "R"
    payload = b"duplicate content"

    # Root level X
    write_file(root / "X" / "file.txt", payload)

    # Folder A with direct child X
    write_file(root / "A" / "X" / "file.txt", payload)

    # Folder B with nested X deeper in the hierarchy
    write_file(root / "B" / "nested" / "X" / "file.txt", payload)

    # Ensure additional distinct content so root is not identical
    write_file(root / "A" / "unique.txt", b"unique A")
    write_file(root / "B" / "nested" / "unique.txt", b"unique B")

    return root


@pytest.mark.parametrize("structure_policy", ["relative", "bag_of_files"])
def test_nested_x_directories_cluster_without_root(tmp_path: Path, structure_policy: str) -> None:
    root = build_nested_x_tree(tmp_path)
    request = ScanRequest(
        root_path=root,
        structure_policy=structure_policy,
    )

    scanner = FolderScanner(request)
    result = scanner.scan()

    groups = compute_similarity_groups(result.fingerprints, request.similarity_threshold)
    classified = classify_groups(groups, request.similarity_threshold, result.fingerprints)

    identical_groups = classified[FolderLabel.IDENTICAL]
    member_sets = [
        {member.relative_path for member in group.members}
        for group, _ in identical_groups
    ]

    expected_members = {"X", "A/X", "B/nested/X"}
    assert expected_members in member_sets, "Identical X folders should cluster together"

    for members in member_sets:
        assert "." not in members, "Root folder should not be grouped with descendants"


def test_similarity_threshold_prevents_false_matches(tmp_path: Path) -> None:
    root = build_nested_x_tree(tmp_path)
    # Add an almost-identical directory with extra file to validate threshold
    write_file(root / "C" / "X" / "file.txt", b"duplicate content")
    write_file(root / "C" / "X" / "extra.txt", b"extra data")

    request = ScanRequest(
        root_path=root,
        similarity_threshold=0.90,
    )

    scanner = FolderScanner(request)
    result = scanner.scan()
    groups = compute_similarity_groups(result.fingerprints, request.similarity_threshold)
    classified = classify_groups(groups, request.similarity_threshold, result.fingerprints)

    identical_sets = [
        {member.relative_path for member in group.members}
        for group, _ in classified[FolderLabel.IDENTICAL]
    ]
    near_sets = [
        {member.relative_path for member in group.members}
        for group, _ in classified[FolderLabel.NEAR_DUPLICATE]
    ]

    assert {"X", "A/X", "B/nested/X"} in identical_sets
    assert {"X", "C/X"} not in identical_sets
    assert all({"X", "C/X"} != members for members in near_sets), "Folder C should fall below 0.90 similarity"


def test_empty_directories_do_not_group(tmp_path: Path) -> None:
    root = tmp_path / "empties"
    (root / "empty_a").mkdir(parents=True)
    (root / "empty_b").mkdir(parents=True)
    (root / "empty_c" / "subdir").mkdir(parents=True)

    request = ScanRequest(root_path=root)
    scanner = FolderScanner(request)
    result = scanner.scan()

    groups = compute_similarity_groups(result.fingerprints, request.similarity_threshold)
    classified = classify_groups(groups, request.similarity_threshold, result.fingerprints)

    assert not classified[FolderLabel.IDENTICAL], "Empty directories should not form identical groups"
    assert not classified[FolderLabel.NEAR_DUPLICATE], "Empty directories should not form near-duplicate groups"


def test_unique_files_remain_isolated(tmp_path: Path) -> None:
    root = tmp_path / "unique"
    write_file(root / "alpha" / "file.txt", b"alpha")
    write_file(root / "beta" / "other.txt", b"beta-different")
    write_file(root / "gamma" / "file.txt", b"gamma-different")

    request = ScanRequest(root_path=root, file_equality="name_size")
    scanner = FolderScanner(request)
    result = scanner.scan()
    groups = compute_similarity_groups(result.fingerprints, request.similarity_threshold)
    classified = classify_groups(groups, request.similarity_threshold, result.fingerprints)

    assert not classified[FolderLabel.IDENTICAL]
    assert not classified[FolderLabel.NEAR_DUPLICATE]


def test_parent_supersedes_children(tmp_path: Path) -> None:
    root = tmp_path / "superset"
    for branch in ("X", "Y"):
        for leaf in ("A", "B"):
            write_file(root / branch / leaf / "payload.bin", b"shared payload")

    request = ScanRequest(root_path=root)
    scanner = FolderScanner(request)
    result = scanner.scan()
    groups = compute_similarity_groups(result.fingerprints, request.similarity_threshold)
    classified = classify_groups(groups, request.similarity_threshold, result.fingerprints)

    identical_sets = [
        {member.relative_path for member in group.members}
        for group, _ in classified[FolderLabel.IDENTICAL]
    ]

    assert {"X", "Y"} in identical_sets
    assert all(
        not (members == {"X", "A"} or members == {"Y", "A"} or members == {"A"} or "A" in members)
        for members in identical_sets
    ), "Child folders should not be grouped when parents already collapse duplicates"
    for group, _ in classified[FolderLabel.IDENTICAL]:
        if {"X", "Y"} == {member.relative_path for member in group.members}:
            for member in group.members:
                assert member.total_bytes > 0
                assert member.file_count > 0


def test_near_duplicate_parent_suppresses_child_identical(tmp_path: Path) -> None:
    root = tmp_path / "variant"
    shared = b"A" * 20
    extra = b"Z" * 2

    write_file(root / "X" / "media" / "file.bin", shared)
    write_file(root / "X" / "docs" / "info.txt", b"info")

    write_file(root / "Y" / "media" / "file.bin", shared)
    write_file(root / "Y" / "docs" / "info.txt", b"info")
    write_file(root / "Y" / "media_abstract" / "extra.bin", extra)

    request = ScanRequest(root_path=root)
    scanner = FolderScanner(request)
    result = scanner.scan()
    groups = compute_similarity_groups(result.fingerprints, request.similarity_threshold)
    classified = classify_groups(groups, request.similarity_threshold, result.fingerprints)

    records: List[Tuple[FolderLabel, GroupRecord]] = []
    for label, groups_for_label in classified.items():
        for group, _ in groups_for_label:
            group_id, members, pairs, divergences = group_to_record(group, label, result.fingerprints)
            member_models = [_to_folder_record(member) for member in members]
            record = GroupRecord(
                group_id=group_id,
                label=label,
                canonical_path=member_models[0].path,
                members=member_models,
                pairwise_similarity=pairs,
                divergences=divergences,
                suppressed_descendants=False,
            )
            records.append((label, record))

    filtered = _suppress_descendant_groups_all(records)
    filtered_sets = [
        {member.relative_path for member in record.members}
        for _, record in filtered
    ]

    assert {"X", "Y"} in filtered_sets, "Parent folders should appear as near duplicates"
    assert all(
        not {"X/media", "Y/media"} <= members for members in filtered_sets
    ), "Child identical folders should be suppressed once parent group exists"
def _to_folder_record(info):
    return FolderRecord(
        path=info.path,
        relative_path=info.relative_path,
        total_bytes=info.total_bytes,
        file_count=info.file_count,
        unstable=info.unstable,
    )
