import difflib
import json
from pathlib import Path
from typing import Any

MAX_SOURCE_CHARS = 64_000
MAX_SOURCE_LINES = 2_000
MAX_DIFF_CHARS = 12_000


def text_snapshot(path: Path, *, existed: bool = True) -> str | None:
    if not existed:
        return ""
    try:
        with path.open(encoding="utf-8", newline="") as file:
            text = file.read(MAX_SOURCE_CHARS + 1)
    except (OSError, UnicodeError):
        return None
    if (
        len(text) > MAX_SOURCE_CHARS
        or len(text.splitlines()) > MAX_SOURCE_LINES
        or "\0" in text
    ):
        return None
    return text


def file_diff(
    before: str | None, path: Path, relative_path: str, *, created: bool = False
) -> dict[str, Any]:
    after = text_snapshot(path)
    if before is None or after is None:
        return {
            "diff": None,
            "diff_truncated": False,
            "diff_unavailable_reason": "File is too large or is not readable UTF-8 text",
        }
    name = relative_path
    if any(character in name for character in "\n\r\t"):
        name = json.dumps(name, ensure_ascii=False)
    lines = difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile="/dev/null" if created else f"a/{name}",
        tofile=f"b/{name}",
    )
    chunks: list[str] = []
    length = 0
    for line in lines:
        if not line.endswith("\n"):
            line += "\n\\ No newline at end of file\n"
        if length + len(line) > MAX_DIFF_CHARS:
            return {"diff": "".join(chunks), "diff_truncated": True}
        chunks.append(line)
        length += len(line)
    return {"diff": "".join(chunks), "diff_truncated": False}
