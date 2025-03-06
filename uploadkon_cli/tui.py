from __future__ import annotations

from pathlib import Path

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)
from rich.table import Table
from rich.text import Text

from .models import UploadRecord


console = Console()


def print_banner() -> None:
    title = Text("UPLOADKON TURBO", style="bold cyan")
    subtitle = Text("parallel uploads | sqlite history | video zip staging", style="green")
    console.print(Panel.fit(Text.assemble(title, "\n", subtitle), border_style="cyan", box=box.DOUBLE))


def print_plan(files: list[Path], db_path: Path, concurrency: int, retries: int, zip_videos: bool) -> None:
    total_bytes = sum(path.stat().st_size for path in files)
    table = Table(box=box.ROUNDED, border_style="bright_black")
    table.add_column("Setting", style="cyan", no_wrap=True)
    table.add_column("Value", style="white")
    table.add_row("Files", str(len(files)))
    table.add_row("Total size", format_bytes(total_bytes))
    table.add_row("Concurrency", str(concurrency))
    table.add_row("Retries", str(retries))
    table.add_row("Video staging", "zip then remove" if zip_videos else "off")
    table.add_row("Database", str(db_path))
    console.print(table)


def make_progress() -> Progress:
    return Progress(
        SpinnerColumn(style="cyan"),
        TextColumn("[bold]{task.fields[name]}", justify="left"),
        BarColumn(bar_width=None, complete_style="green", finished_style="bright_green"),
        MofNCompleteColumn(),
        TransferSpeedColumn(),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        TextColumn("[magenta]{task.fields[status]}"),
        console=console,
        transient=False,
    )


def add_upload_task(progress: Progress, name: str, total: int, status: str) -> TaskID:
    return progress.add_task("upload", total=max(total, 1), name=name, status=status)


def print_results(records: list[UploadRecord], db_path: Path) -> None:
    ok_count = sum(record.status == "ok" for record in records)
    failed_count = len(records) - ok_count
    table = Table(title="Upload Results", box=box.ROUNDED, border_style="bright_black")
    table.add_column("Status", no_wrap=True)
    table.add_column("File")
    table.add_column("Uploaded As")
    table.add_column("Attempts", justify="right")
    table.add_column("Time", justify="right")
    table.add_column("Link")

    for record in records:
        status = "[green]OK[/green]" if record.status == "ok" else "[red]FAILED[/red]"
        uploaded_as = record.uploaded_file_name
        if record.zipped:
            uploaded_as = f"{uploaded_as} [yellow](zip)[/yellow]"
        table.add_row(
            status,
            record.file_name,
            uploaded_as,
            str(record.attempts),
            f"{record.elapsed_ms / 1000:.1f}s",
            record.direct_url or record.error or "",
        )

    console.print(table)
    color = "green" if failed_count == 0 else "yellow"
    console.print(
        f"[{color}]Saved {len(records)} result(s) to {db_path} "
        f"({ok_count} ok, {failed_count} failed).[/{color}]"
    )


def format_bytes(value: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.1f} {unit}" if unit != "B" else f"{int(amount)} B"
        amount /= 1024
    return f"{value} B"
