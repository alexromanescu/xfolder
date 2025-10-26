from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Optional, Tuple


FileCacheKey = Tuple[int, int, int, float]


class FileHashCache:
    """Thread-safe SQLite-backed cache for file hashes."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS file_hashes (
                    device INTEGER NOT NULL,
                    inode INTEGER NOT NULL,
                    size INTEGER NOT NULL,
                    mtime REAL NOT NULL,
                    sha256 TEXT NOT NULL,
                    PRIMARY KEY (device, inode, size, mtime)
                )
                """
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def get(self, key: FileCacheKey) -> Optional[str]:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "SELECT sha256 FROM file_hashes WHERE device=? AND inode=? AND size=? AND mtime=?",
                key,
            )
            row = cur.fetchone()
        if row:
            return row[0]
        return None

    def set(self, key: FileCacheKey, value: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO file_hashes (device, inode, size, mtime, sha256)
                VALUES (?, ?, ?, ?, ?)
                """,
                (*key, value),
            )
            conn.commit()

