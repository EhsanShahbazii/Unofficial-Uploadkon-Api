from __future__ import annotations

import asyncio
import mimetypes
import random
import time
from typing import Callable

import httpx

from .config import UPLOAD_URL, USER_AGENTS
from .models import StagedFile, UploadRecord
from .parser import UploadParseError, parse_upload_response

ProgressCallback = Callable[[int], None]
ProgressResetCallback = Callable[[int, int], None]
AttemptCallback = Callable[[int, str], None]


class ProgressFile:
    def __init__(self, file_obj, callback: ProgressCallback | None) -> None:
        self._file_obj = file_obj
        self._callback = callback

    def read(self, size: int = -1) -> bytes:
        chunk = self._file_obj.read(size)
        if chunk and self._callback:
            self._callback(len(chunk))
        return chunk

    def seek(self, offset: int, whence: int = 0) -> int:
        return self._file_obj.seek(offset, whence)

    def tell(self) -> int:
        return self._file_obj.tell()

    def fileno(self) -> int:
        return self._file_obj.fileno()

    @property
    def name(self) -> str:
        return self._file_obj.name


def choose_user_agent(override: str | None, randomize: bool) -> str:
    if override:
        return override
    if randomize:
        return random.choice(USER_AGENTS)
    return USER_AGENTS[0]


def make_headers(
    cookie: str | None,
    user_agent: str | None,
    randomize_user_agent: bool,
) -> dict[str, str]:
    headers = {
        "User-Agent": choose_user_agent(user_agent, randomize_user_agent),
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": UPLOAD_URL,
        "Pragma": "no-cache",
        "Cache-Control": "no-cache",
    }
    if cookie:
        headers["Cookie"] = cookie
    return headers


async def warm_session(
    client: httpx.AsyncClient,
    cookie: str | None,
    user_agent: str | None,
    randomize_user_agent: bool,
) -> None:
    try:
        await client.get(
            UPLOAD_URL,
            headers=make_headers(cookie, user_agent, randomize_user_agent),
        )
    except httpx.HTTPError:
        pass


async def upload_one(
    client: httpx.AsyncClient,
    staged: StagedFile,
    retries: int,
    cookie: str | None,
    user_agent: str | None,
    randomize_user_agent: bool,
    progress: ProgressCallback | None = None,
    reset_progress: ProgressResetCallback | None = None,
    on_attempt: AttemptCallback | None = None,
) -> UploadRecord:
    started = time.perf_counter()
    last_error: str | None = None
    attempts_used = 0

    for attempt in range(1, retries + 1):
        attempts_used = attempt
        selected_user_agent = choose_user_agent(user_agent, randomize_user_agent)
        if on_attempt:
            on_attempt(attempt, selected_user_agent)
        if reset_progress:
            reset_progress(staged.upload_size, 0)

        try:
            mime_type = mimetypes.guess_type(staged.upload_name)[0] or "application/octet-stream"
            headers = make_headers(cookie, selected_user_agent, randomize_user_agent=False)
            with staged.upload_path.open("rb") as raw_file:
                tracked_file = ProgressFile(raw_file, progress)
                response = await client.post(
                    UPLOAD_URL,
                    headers=headers,
                    data={"submitr": "1", "ajax": "1"},
                    files={"file": (staged.upload_name, tracked_file, mime_type)},
                )
            response.raise_for_status()
            parsed = parse_upload_response(response.text)
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            if reset_progress:
                reset_progress(staged.upload_size, staged.upload_size)
            return UploadRecord(
                file_path=staged.source_path,
                file_name=staged.source_path.name,
                file_size=staged.source_size,
                file_mtime_ns=staged.source_mtime_ns,
                uploaded_file_name=staged.upload_name,
                uploaded_file_size=staged.upload_size,
                zipped=staged.zipped,
                status="ok",
                direct_url=parsed.direct_url,
                delete_url=parsed.delete_url,
                error=None,
                attempts=attempts_used,
                elapsed_ms=elapsed_ms,
            )
        except (httpx.HTTPError, OSError, UploadParseError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < retries:
                await asyncio.sleep(min(2 ** (attempt - 1), 12) + random.uniform(0.1, 0.7))

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return UploadRecord(
        file_path=staged.source_path,
        file_name=staged.source_path.name,
        file_size=staged.source_size,
        file_mtime_ns=staged.source_mtime_ns,
        uploaded_file_name=staged.upload_name,
        uploaded_file_size=staged.upload_size,
        zipped=staged.zipped,
        status="failed",
        direct_url=None,
        delete_url=None,
        error=last_error or "Unknown upload error",
        attempts=attempts_used,
        elapsed_ms=elapsed_ms,
    )
