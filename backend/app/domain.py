from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FolderInfo:
    path: str
    relative_path: str
    total_bytes: int
    file_count: int
    unstable: bool = False


@dataclass
class GroupInfo:
    group_id: str
    label: str
    canonical_path: str
    members: list[FolderInfo]
    pairwise_similarity: list
    divergences: list
    suppressed_descendants: bool = False
