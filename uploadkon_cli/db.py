from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import UploadRecord


SCHEMA_COLUMNS = [
    "id",
    "file_path",
    "file_name",
    "file_size",
    "file_mtime_ns",
    "uploaded_file_name",
    "uploaded_file_size",
    "zipped",
    "status",
    "direct_url",
    "delete_url",
    "error",
    "attempts",
    "elapsed_ms",
    "uploaded_at",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    ensure_schema(conn)
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS uploads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT NOT NULL,
            file_name TEXT NOT NULL,
            file_size INTEGER NOT NULL,
            file_mtime_ns INTEGER NOT NULL,
            uploaded_file_name TEXT NOT NULL,
            uploaded_file_size INTEGER NOT NULL,
            zipped INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL,
            direct_url TEXT,
            delete_url TEXT,
            error TEXT,
            attempts INTEGER NOT NULL DEFAULT 1,
            elapsed_ms INTEGER NOT NULL,
            uploaded_at TEXT NOT NULL
        )
        """
    )
    migrate_legacy_schema(conn)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_uploads_file_path ON uploads(file_path)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_uploads_direct_url ON uploads(direct_url)")
    conn.commit()


def migrate_legacy_schema(conn: sqlite3.Connection) -> None:
    rows = conn.execute("PRAGMA table_info(uploads)").fetchall()
    columns = [row[1] for row in rows]
    unwanted = {"forum_url", "response_json"}
    missing_required = {"uploaded_file_name", "uploaded_file_size", "zipped", "attempts"} - set(columns)
    if not (unwanted & set(columns) or missing_required):
        return

    conn.execute("ALTER TABLE uploads RENAME TO uploads_legacy")
    conn.execute(
        """
        CREATE TABLE uploads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT NOT NULL,
            file_name TEXT NOT NULL,
            file_size INTEGER NOT NULL,
            file_mtime_ns INTEGER NOT NULL,
            uploaded_file_name TEXT NOT NULL,
            uploaded_file_size INTEGER NOT NULL,
            zipped INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL,
            direct_url TEXT,
            delete_url TEXT,
            error TEXT,
            attempts INTEGER NOT NULL DEFAULT 1,
            elapsed_ms INTEGER NOT NULL,
            uploaded_at TEXT NOT NULL
        )
        """
    )

    legacy_columns = set(columns)
    select_uploaded_name = (
        "uploaded_file_name" if "uploaded_file_name" in legacy_columns else "file_name"
    )
    select_uploaded_size = (
        "uploaded_file_size" if "uploaded_file_size" in legacy_columns else "file_size"
    )
    select_zipped = "zipped" if "zipped" in legacy_columns else "0"
    select_attempts = "attempts" if "attempts" in legacy_columns else "1"

    conn.execute(
        f"""
        INSERT INTO uploads (
            id, file_path, file_name, file_size, file_mtime_ns,
            uploaded_file_name, uploaded_file_size, zipped, status,
            direct_url, delete_url, error, attempts, elapsed_ms, uploaded_at
        )
        SELECT
            id, file_path, file_name, file_size, file_mtime_ns,
            {select_uploaded_name}, {select_uploaded_size}, {select_zipped}, status,
            direct_url, delete_url, error, {select_attempts}, elapsed_ms, uploaded_at
        FROM uploads_legacy
        """
    )
    conn.execute("DROP TABLE uploads_legacy")


def save_record(conn: sqlite3.Connection, record: UploadRecord) -> None:
    conn.execute(
        """
        INSERT INTO uploads (
            file_path, file_name, file_size, file_mtime_ns,
            uploaded_file_name, uploaded_file_size, zipped, status,
            direct_url, delete_url, error, attempts, elapsed_ms, uploaded_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(record.file_path),
            record.file_name,
            record.file_size,
            record.file_mtime_ns,
            record.uploaded_file_name,
            record.uploaded_file_size,
            int(record.zipped),
            record.status,
            record.direct_url,
            record.delete_url,
            record.error,
            record.attempts,
            record.elapsed_ms,
            utc_now(),
        ),
    )
    conn.commit()


def already_uploaded(conn: sqlite3.Connection, path: Path) -> bool:
    stat = path.stat()
    row = conn.execute(
        """
        SELECT 1
        FROM uploads
        WHERE file_path = ?
          AND file_size = ?
          AND file_mtime_ns = ?
          AND status = 'ok'
        LIMIT 1
        """,
        (str(path), stat.st_size, stat.st_mtime_ns),
    ).fetchone()
    return row is not None
