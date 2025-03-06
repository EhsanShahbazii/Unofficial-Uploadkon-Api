from __future__ import annotations

import html
import json
from html.parser import HTMLParser

from .models import ParsedLinks


class UploadParseError(RuntimeError):
    pass


class TextareaParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._current_id: str | None = None
        self._buffer: list[str] = []
        self.values: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "textarea":
            return
        attr_map = {name.lower(): value for name, value in attrs}
        textarea_id = attr_map.get("id")
        if textarea_id:
            self._current_id = textarea_id
            self._buffer = []

    def handle_data(self, data: str) -> None:
        if self._current_id is not None:
            self._buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "textarea" and self._current_id is not None:
            self.values[self._current_id] = "".join(self._buffer).strip()
            self._current_id = None
            self._buffer = []


def parse_upload_response(response_text: str) -> ParsedLinks:
    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError as exc:
        raise UploadParseError(f"Upload response is not JSON: {exc}") from exc

    items = payload if isinstance(payload, list) else [payload]
    html_fragment = None
    for item in items:
        if not isinstance(item, dict):
            continue
        html_fragment = item.get("message_content") or item.get("i")
        if html_fragment:
            break

    if not isinstance(html_fragment, str):
        raise UploadParseError("Upload response did not contain message_content or i HTML.")

    parser = TextareaParser()
    parser.feed(html_fragment)
    values = {key: html.unescape(value) for key, value in parser.values.items()}

    direct_url = values.get("file1")
    if not direct_url:
        raise UploadParseError("Could not find the direct file URL in textarea#file1.")

    return ParsedLinks(direct_url=direct_url, delete_url=values.get("delCode"))
