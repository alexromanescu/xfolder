from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, validator

from .domain import FolderInfo

class FileEqualityMode(str, Enum):
    NAME_SIZE = "name_size"
    SHA256 = "sha256"


class StructurePolicy(str, Enum):
    RELATIVE = "relative"
    BAG_OF_FILES = "bag_of_files"


class WarningType(str, Enum):
    PERMISSION = "permission"
    UNSTABLE = "unstable"
    IO_ERROR = "io_error"


class FolderLabel(str, Enum):
    IDENTICAL = "identical"
    NEAR_DUPLICATE = "near_duplicate"
    PARTIAL_OVERLAP = "partial_overlap"


class ScanStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ScanRequest(BaseModel):
    root_path: Path
    include: List[str] = Field(default_factory=list)
    exclude: List[str] = Field(default_factory=list)
    file_equality: FileEqualityMode = FileEqualityMode.NAME_SIZE
    similarity_threshold: float = Field(default=0.80, ge=0.0, le=1.0)
    force_case_insensitive: bool = False
    structure_policy: StructurePolicy = StructurePolicy.RELATIVE
    concurrency: Optional[int] = Field(default=None, ge=1, le=32)
    deletion_enabled: bool = False
    include_matrix: bool = False
    include_treemap: bool = False

    @validator("root_path", pre=True)
    def normalize_root(cls, value: str | Path) -> Path:
        return Path(value).expanduser().resolve()


class FileRecord(BaseModel):
    path: Path
    relative_path: str
    size: int
    mtime: float
    sha256: Optional[str] = None


class FolderRecord(BaseModel):
    path: str
    relative_path: str
    total_bytes: int
    file_count: int
    unstable: bool = False


class PairwiseSimilarity(BaseModel):
    a: int
    b: int
    similarity: float


class DivergenceRecord(BaseModel):
    path_a: str
    path_b: str
    delta_bytes: int


class GroupRecord(BaseModel):
    group_id: str
    label: FolderLabel
    canonical_path: str
    members: List[FolderRecord]
    pairwise_similarity: List[PairwiseSimilarity]
    divergences: List[DivergenceRecord]
    suppressed_descendants: bool = False


class WarningRecord(BaseModel):
    path: Path
    type: WarningType
    message: str


class PhaseProgress(BaseModel):
    name: str
    status: Literal["pending", "running", "completed"]
    progress: Optional[float] = None


class PhaseTiming(BaseModel):
    phase: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None


class ScanProgress(BaseModel):
    scan_id: str
    status: ScanStatus
    started_at: datetime
    completed_at: Optional[datetime] = None
    warnings: List[WarningRecord] = Field(default_factory=list)
    root_path: Path
    stats: Dict[str, int] = Field(default_factory=dict)
    progress: Optional[float] = None
    eta_seconds: Optional[int] = None
    phase: str = ""
    last_path: Optional[str] = None
    phases: List[PhaseProgress] = Field(default_factory=list)
    include_matrix: bool = False
    include_treemap: bool = False


class ExportFilters(BaseModel):
    include: List[str] = Field(default_factory=list)
    exclude: List[str] = Field(default_factory=list)


class ExportHeader(BaseModel):
    schema_version: int = 1
    generated_at: datetime
    root: Path
    file_equality: FileEqualityMode
    min_similarity: float
    structure_policy: StructurePolicy
    filters: ExportFilters = Field(default_factory=ExportFilters)


class DeletionPlanPayload(BaseModel):
    paths: List[str]


class DeletionPlan(BaseModel):
    plan_id: str
    token: str
    reclaimable_bytes: int
    queue: List[str]
    root: Path
    quarantine_root: Path
    expires_at: datetime


class DeletionResult(BaseModel):
    plan_id: str
    moved_count: int
    bytes_moved: int
    quarantine_root: Path
    root: Path


class ConfirmDeletionPayload(BaseModel):
    token: str


class DiffEntry(BaseModel):
    path: str
    bytes: int


class MismatchEntry(BaseModel):
    path: str
    left_bytes: int
    right_bytes: int


class GroupDiff(BaseModel):
    left: FolderRecord
    right: FolderRecord
    only_left: List[DiffEntry]
    only_right: List[DiffEntry]
    mismatched: List[MismatchEntry]


class SimilarityMatrixEntry(BaseModel):
    group_id: str
    label: FolderLabel
    left: FolderRecord
    right: FolderRecord
    similarity: float
    combined_bytes: int
    reclaimable_bytes: int


class SimilarityMatrixResponse(BaseModel):
    scan_id: str
    generated_at: datetime
    root_path: Path
    min_similarity: float
    total_entries: int
    entries: List[SimilarityMatrixEntry]


class TreemapNode(BaseModel):
    path: str
    name: str
    total_bytes: int
    duplicate_bytes: int
    identical_groups: int
    near_groups: int
    children: List["TreemapNode"] = Field(default_factory=list)


class TreemapResponse(BaseModel):
    scan_id: str
    generated_at: datetime
    root_path: Path
    tree: TreemapNode


class LogEntry(BaseModel):
    timestamp: datetime
    level: str
    level_no: int
    message: str
    logger: str


class ResourceStats(BaseModel):
    cpu_cores: int
    load_1m: float
    process_rss_bytes: int
    process_read_bytes: Optional[int] = None
    process_write_bytes: Optional[int] = None


class ResourceSample(ResourceStats):
    timestamp: datetime


class ScanMetrics(BaseModel):
    scan_id: str
    root_path: Path
    started_at: datetime
    completed_at: Optional[datetime]
    worker_count: int
    bytes_scanned: int
    phase_timings: List[PhaseTiming]
    resource_samples: List[ResourceSample]


class FolderEntry(BaseModel):
    path: str
    bytes: int


class MemberContents(BaseModel):
    relative_path: str
    entries: List[FolderEntry]


class GroupContents(BaseModel):
    group_id: str
    canonical: MemberContents
    duplicates: List[MemberContents]


@dataclass
class DirectoryFingerprint:
    folder: FolderInfo
    file_weights: Dict[str, int]


TreemapNode.update_forward_refs()
