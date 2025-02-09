from __future__ import annotations

import argparse
import asyncio
import os
import sqlite3
import tempfile
import time
from pathlib import Path

import httpx

from .config import DEFAULT_DB
from .db import already_uploaded, connect_db, save_record
from .files import cleanup_staged_file, collect_paths, split_user_paths, stage_for_upload
from .http import upload_one, warm_session
from .models import UploadRecord
from .tui import add_upload_task, console, make_progress, print_banner, print_plan, print_results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="uploadkon",
        description=(
            "Upload files to uploadkon.ir with parallel workers, retry/backoff, "
            "video-to-zip staging, Rich progress bars, and SQLite link storage."
        ),
    )
    parser.add_argument("paths", nargs="*", help="File or directory paths to upload.")
    parser.add_argument("--db", default=DEFAULT_DB, help=f"SQLite DB path. Default: {DEFAULT_DB}")
    parser.add_argument(
        "-c",
        "--concurrency",
        type=int,
        default=3,
        help="Number of simultaneous uploads. Default: 3",
    )
    parser.add_argument(
        "-r",
        "--recursive",
        action="store_true",
        help="When a directory is passed, include files in subdirectories.",
    )
    parser.add_argument("--glob", default="*", help="Glob used for directories. Default: *")
    parser.add_argument("--timeout", type=float, default=180.0, help="Request timeout seconds.")
    parser.add_argument("--retries", type=int, default=3, help="Attempts per file. Default: 3")
    parser.add_argument(
        "--skip-uploaded",
        action="store_true",
        help="Skip files already saved successfully with the same path, size, and mtime.",
    )
    parser.add_argument(
        "--cookie",
        default=os.environ.get("UPLOADKON_COOKIE"),
        help="Optional Cookie header. Can also be set with UPLOADKON_COOKIE.",
    )
    parser.add_argument("--user-agent", help="Use one exact User-Agent instead of the built-in pool.")
    parser.add_argument(
        "--no-random-user-agent",
        action="store_true",
        help="Disable per-attempt random User-Agent selection.",
    )
    parser.add_argument(
        "--no-zip-videos",
        action="store_true",
        help="Do not zip video files before upload.",
    )
    parser.add_argument(
        "--tmp-dir",
        help="Directory for temporary video zip files. Defaults to the system temp directory.",
    )
    return parser


async def run_uploads(args: argparse.Namespace, files: list[Path]) -> int:
    db_path = Path(args.db).expanduser().resolve()
    conn = connect_db(db_path)
    write_lock = asyncio.Lock()

    if args.skip_uploaded:
        original_count = len(files)
        files = [path for path in files if not already_uploaded(conn, path)]
        skipped = original_count - len(files)
        if skipped:
            console.print(f"[yellow]Skipped {skipped} already uploaded file(s).[/yellow]")

    if not files:
        console.print("[yellow]No files to upload.[/yellow]")
        conn.close()
        return 0

    print_plan(
        files,
        db_path=db_path,
        concurrency=args.concurrency,
        retries=args.retries,
        zip_videos=not args.no_zip_videos,
    )

    semaphore = asyncio.Semaphore(args.concurrency)
    timeout = httpx.Timeout(args.timeout, connect=30.0)
    limits = httpx.Limits(
        max_connections=max(args.concurrency, 1),
        max_keepalive_connections=max(args.concurrency, 1),
    )
    results: list[UploadRecord] = []
    temp_parent = Path(args.tmp_dir).expanduser().resolve() if args.tmp_dir else None

    with tempfile.TemporaryDirectory(dir=temp_parent) as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        async with httpx.AsyncClient(
            timeout=timeout,
            limits=limits,
            follow_redirects=True,
        ) as client:
            await warm_session(
                client,
                cookie=args.cookie,
                user_agent=args.user_agent,
                randomize_user_agent=not args.no_random_user_agent,
            )

            progress = make_progress()
            with progress:

                async def run_one(path: Path) -> UploadRecord:
                    task_id = add_upload_task(
                        progress,
                        name=path.name,
                        total=max(path.stat().st_size, 1),
                        status="queued",
                    )

                    async with semaphore:
                        staged = None
                        started = time.perf_counter()
                        try:
                            progress.update(task_id, status="staging")
                            staged = stage_for_upload(
                                path,
                                temp_dir=temp_dir,
                                zip_videos=not args.no_zip_videos,
                            )
                            if staged.zipped:
                                progress.update(
                                    task_id,
                                    total=max(staged.upload_size, 1),
                                    completed=0,
                                    status="zipped",
                                )

                            record = await upload_one(
                                client,
                                staged,
                                retries=args.retries,
                                cookie=args.cookie,
                                user_agent=args.user_agent,
                                randomize_user_agent=not args.no_random_user_agent,
                                progress=lambda delta: progress.advance(task_id, delta),
                                reset_progress=lambda total, completed: progress.update(
                                    task_id,
                                    total=max(total, 1),
                                    completed=completed,
                                ),
                                on_attempt=lambda attempt, _ua: progress.update(
                                    task_id,
                                    status=f"try {attempt}/{args.retries}",
                                ),
                            )
                        except Exception as exc:
                            stat = path.stat()
                            record = UploadRecord(
                                file_path=path,
                                file_name=path.name,
                                file_size=stat.st_size,
                                file_mtime_ns=stat.st_mtime_ns,
                                uploaded_file_name=path.name,
                                uploaded_file_size=stat.st_size,
                                zipped=False,
                                status="failed",
                                direct_url=None,
                                delete_url=None,
                                error=f"{type(exc).__name__}: {exc}",
                                attempts=0,
                                elapsed_ms=int((time.perf_counter() - started) * 1000),
                            )
                        finally:
                            if staged is not None:
                                cleanup_staged_file(staged)

                        async with write_lock:
                            save_record(conn, record)
                            results.append(record)

                        if record.status == "ok":
                            progress.update(
                                task_id,
                                completed=max(record.uploaded_file_size, 1),
                                status="done",
                            )
                        else:
                            progress.update(task_id, status="failed")
                        return record

                await asyncio.gather(*(run_one(path) for path in files))

    conn.close()
    results.sort(key=lambda record: record.file_name.lower())
    print_results(results, db_path)
    return 1 if any(record.status != "ok" for record in results) else 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    args.concurrency = max(1, args.concurrency)
    args.retries = max(1, args.retries)

    print_banner()

    inputs = args.paths
    if not inputs:
        raw = console.input("[bold cyan]File or directory path(s): [/bold cyan]")
        inputs = split_user_paths(raw)

    try:
        files = collect_paths(inputs, recursive=args.recursive, glob_pattern=args.glob)
    except (FileNotFoundError, OSError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        return 2

    try:
        return asyncio.run(run_uploads(args, files))
    except (KeyboardInterrupt, sqlite3.Error) as exc:
        console.print(f"[red]Stopped:[/red] {exc}")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
