from __future__ import annotations

import shelve
from pathlib import Path
from typing import Dict

from .domain import FolderInfo
from .models import DirectoryFingerprint


class FingerprintStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    @classmethod
    def write(cls, db_path: Path, fingerprints: Dict[str, DirectoryFingerprint]) -> "FingerprintStore":
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with shelve.open(str(db_path), flag="n") as database:
            for key, fingerprint in fingerprints.items():
                database[key] = fingerprint
        return cls(db_path)

    def get(self, relative_path: str) -> DirectoryFingerprint:
        with shelve.open(str(self.db_path), flag="r") as database:
            if relative_path not in database:
                raise KeyError(relative_path)
            return database[relative_path]
