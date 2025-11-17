from __future__ import annotations

from .domain import FolderInfo, GroupInfo
from .models import DivergenceRecord, FolderRecord, GroupRecord, PairwiseSimilarity


def folder_info_to_record(info: FolderInfo) -> FolderRecord:
    return FolderRecord(
        path=info.path,
        relative_path=info.relative_path,
        total_bytes=info.total_bytes,
        file_count=info.file_count,
        unstable=info.unstable,
    )


def group_info_to_record(info: GroupInfo) -> GroupRecord:
    members = [folder_info_to_record(member) for member in info.members]
    return GroupRecord(
        group_id=info.group_id,
        label=info.label,
        canonical_path=info.canonical_path,
        members=members,
        pairwise_similarity=list(info.pairwise_similarity),
        divergences=list(info.divergences),
        suppressed_descendants=info.suppressed_descendants,
    )
