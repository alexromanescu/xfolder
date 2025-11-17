from __future__ import annotations

from dataclasses import dataclass
from typing import List


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
    label: "FolderLabel"
    canonical_path: str
    members: List[FolderInfo]
    pairwise_similarity: List["PairwiseSimilarity"]
    divergences: List["DivergenceRecord"]
    suppressed_descendants: bool = False
