from __future__ import annotations

import os
import shlex
import tempfile
import zipfile
from pathlib import Path
from typing import Iterable

from .config import VIDEO_EXTENSIONS
from .models import StagedFile


def split_user_paths(raw: str) -> list[str]:
    raw = raw.strip()
    if not raw:
        return []
    stripped = raw.strip("\"'")
    if Path(stripped).exists():
        return [stripped]
    return [part.strip("\"'") for part in shlex.split(raw, posix=False)]


def collect_paths(inputs: Iterable[str], recursive: bool, glob_pattern: str) -> list[Path]:
    files: list[Path] = []
    for value in inputs:
        path = Path(value).expanduser()
        if path.is_file():
            files.append(path.resolve())
            continue
        if path.is_dir():
            iterator = path.rglob(glob_pattern) if recursive else path.glob(glob_pattern)
            files.extend(item.resolve() for item in iterator if item.is_file())
            continue
        raise FileNotFoundError(f"Path does not exist or is not a file/directory: {value}")
    return sorted(dict.fromkeys(files))


def is_video(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXTENSIONS


def stage_for_upload(path: Path, temp_dir: Path, zip_videos: bool) -> StagedFile:
    stat = path.stat()
    if zip_videos and is_video(path):
        temp_dir.mkdir(parents=True, exist_ok=True)
        safe_stem = "".join(char if char.isalnum() or char in "._-" else "_" for char in path.stem)
        fd, zip_name = tempfile.mkstemp(
            prefix=f"{safe_stem}_",
            suffix=".zip",
            dir=temp_dir,
        )
        os.close(fd)
        zip_path = Path(zip_name)
        try:
            with zipfile.ZipFile(zip_path, mode="w", compression=zipfile.ZIP_STORED) as archive:
                archive.write(path, arcname=path.name)
        except Exception:
            zip_path.unlink(missing_ok=True)
            raise

        zip_stat = zip_path.stat()
        return StagedFile(
            source_path=path,
            upload_path=zip_path,
            upload_name=f"{path.name}.zip",
            source_size=stat.st_size,
            upload_size=zip_stat.st_size,
            source_mtime_ns=stat.st_mtime_ns,
            is_temp=True,
            zipped=True,
        )

    return StagedFile(
        source_path=path,
        upload_path=path,
        upload_name=path.name,
        source_size=stat.st_size,
        upload_size=stat.st_size,
        source_mtime_ns=stat.st_mtime_ns,
        is_temp=False,
        zipped=False,
    )


def cleanup_staged_file(staged: StagedFile) -> None:
    if staged.is_temp:
        staged.upload_path.unlink(missing_ok=True)
