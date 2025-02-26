from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ParsedLinks:
    direct_url: str
    delete_url: str | None


@dataclass(frozen=True)
class StagedFile:
    source_path: Path
    upload_path: Path
    upload_name: str
    source_size: int
    upload_size: int
    source_mtime_ns: int
    is_temp: bool
    zipped: bool


@dataclass(frozen=True)
class UploadRecord:
    file_path: Path
    file_name: str
    file_size: int
    file_mtime_ns: int
    uploaded_file_name: str
    uploaded_file_size: int
    zipped: bool
    status: str
    direct_url: str | None
    delete_url: str | None
    error: str | None
    attempts: int
    elapsed_ms: int
