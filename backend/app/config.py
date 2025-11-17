from __future__ import annotations

import os
from pathlib import Path
from typing import List

from pydantic import BaseModel, Field, validator


class ScannerSettings(BaseModel):
    root_path: Path = Field(..., description="Root folder to scan")
    include: List[str] = Field(default_factory=list, description="Glob patterns to include")
    exclude: List[str] = Field(default_factory=lambda: [
        ".git/**",
        "node_modules/**",
        "__pycache__/**",
        ".cache/**",
        "Thumbs.db",
        ".DS_Store",
    ])
    similarity_threshold: float = Field(default=0.80, ge=0.0, le=1.0)
    file_equality: str = Field(default="name_size", pattern="^(name_size|sha256)$")
    force_case_insensitive: bool = False
    structure_policy: str = Field(default="relative", pattern="^(relative|bag_of_files)$")
    concurrency: int | None = Field(default=None, ge=1, le=32)
    deletion_enabled: bool = False

    @validator("root_path", pre=True)
    def expand_root(cls, value: str | Path) -> Path:
        return Path(value).expanduser().resolve()

    @validator("include", "exclude", pre=True)
    def ensure_list(cls, value):
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        return list(value)

    @validator("similarity_threshold", pre=True)
    def default_similarity(cls, value):
        if value is None:
            return 0.80
        return value


class AppConfig(BaseModel):
    listen_host: str = Field(default="0.0.0.0")
    listen_port: int = Field(default=8080)
    config_path: Path = Field(default=Path("/config"))
    cache_db_path: Path | None = None
    log_level: str = Field(default="INFO")
    log_stream_enabled: bool = Field(default=False)
    metrics_enabled: bool = Field(default=False)
    matrix_max_entries: int = Field(default=1000, ge=0)
    matrix_min_reclaim_bytes: int = Field(default=0, ge=0)
    matrix_include_identical: bool = Field(default=False)

    @classmethod
    def from_env(cls) -> "AppConfig":
        root = os.getenv("XFS_CONFIG_PATH", "/config")
        cache = os.getenv("XFS_CACHE_DB")
        log_level = os.getenv("XFS_LOG_LEVEL", "INFO").upper()
        log_stream = os.getenv("XFS_LOG_STREAM_ENABLED", "0") in {"1", "true", "TRUE"}
        metrics_enabled = os.getenv("XFS_METRICS_ENABLED", "0") in {"1", "true", "TRUE"}
        matrix_max = int(os.getenv("XFS_MATRIX_MAX_ENTRIES", "1000"))
        matrix_min_reclaim = int(os.getenv("XFS_MATRIX_MIN_RECLAIM_BYTES", "0"))
        matrix_include_identical = os.getenv("XFS_MATRIX_INCLUDE_IDENTICAL", "0") in {"1", "true", "TRUE"}
        return cls(
            listen_host=os.getenv("XFS_LISTEN_HOST", "0.0.0.0"),
            listen_port=int(os.getenv("XFS_LISTEN_PORT", "8080")),
            config_path=Path(root).expanduser().resolve(),
            cache_db_path=Path(cache).expanduser().resolve() if cache else None,
            log_level=log_level,
            log_stream_enabled=log_stream,
            metrics_enabled=metrics_enabled,
            matrix_max_entries=matrix_max,
            matrix_min_reclaim_bytes=matrix_min_reclaim,
            matrix_include_identical=matrix_include_identical,
        )
