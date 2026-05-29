from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional


@dataclass
class EmojiItem:
    id: int
    source_path: str
    rel_path: str
    file_type: str
    ext: str
    size: int
    sha256: str
    scanned_at: str
    preview_path: Optional[str] = None
    # For converted V1MMWX/WXGF items, source_path points to the readable
    # cache image while original_path keeps the true WeChat/source file path
    # for audit/export logs.
    original_path: Optional[str] = None
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ExportRecord:
    index: int
    original_path: str
    export_path: Optional[str]
    file_format: str
    file_size: int
    sha256: str
    duplicate: bool
    status: str
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ScanStats:
    scanned_files: int = 0
    recognized: int = 0
    unreadable: int = 0
    unsupported: int = 0
    encrypted_v1mmwx: int = 0
    wxgf: int = 0
