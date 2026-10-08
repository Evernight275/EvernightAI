import os

import pytest

from EvernightAI.infra.adapters.tool.restricted_filesystem import (
    RestrictedAppendTextFileTool,
    RestrictedApplyTextPatchTool,
    RestrictedWriteJsonFileTool,
    RestrictedWriteTextFileTool,
)
from EvernightAI.infra.adapters.tool.text_diff import MAX_DIFF_CHARS, MAX_SOURCE_CHARS


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["write", "append", "patch", "json"])
async def test_file_tools_return_actual_before_and_after_diff(tmp_path, operation):
    path = tmp_path / "note.txt"
    path.write_bytes(b"old\n")
    match operation:
        case "append":
            tool = RestrictedAppendTextFileTool(root_directory=tmp_path)
            arguments = {"content": "new\n"}
            expected = "old\nnew\n"
        case "patch":
            tool = RestrictedApplyTextPatchTool(root_directory=tmp_path)
            arguments = {"old_text": "old", "new_text": "new"}
            expected = "new\n"
        case "json":
            tool = RestrictedWriteJsonFileTool(
                root_directory=tmp_path, allow_overwrite=True
            )
            arguments = {"data": {"new": True}}
            expected = '{\n  "new": true\n}\n'
        case _:
            tool = RestrictedWriteTextFileTool(
                root_directory=tmp_path, allow_overwrite=True
            )
            arguments = {"content": "new\n"}
            expected = "new\n"

    result = await tool.execute({"path": "note.txt", **arguments})

    assert path.read_bytes() == expected.encode()
    assert result["diff"].startswith("--- a/note.txt\n+++ b/note.txt\n@@ ")
    assert "+new\n" in result["diff"] or '+  "new": true\n' in result["diff"]
    assert (" old\n" if operation == "append" else "-old\n") in result["diff"]
    assert result["diff_truncated"] is False
    path.write_text("later change", encoding="utf-8")
    assert "later change" not in result["diff"]


@pytest.mark.asyncio
async def test_diff_preserves_crlf_and_missing_final_newline(tmp_path):
    (tmp_path / "note.txt").write_bytes(b"old\r\nlast")
    result = await RestrictedWriteTextFileTool(
        root_directory=tmp_path, allow_overwrite=True
    ).execute({"path": "note.txt", "content": "new\nlast"})
    assert "-old\r\n" in result["diff"]
    assert "+new\n" in result["diff"]
    assert " last\n\\ No newline at end of file\n" in result["diff"]


@pytest.mark.asyncio
async def test_diff_is_empty_for_unchanged_content(tmp_path):
    (tmp_path / "note.txt").write_text("same", encoding="utf-8")
    result = await RestrictedWriteTextFileTool(
        root_directory=tmp_path, allow_overwrite=True
    ).execute({"path": "note.txt", "content": "same"})
    assert result["diff"] == ""
    assert result["diff_truncated"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "original",
    [b"\xff", b"a\0b", b"x" * (MAX_SOURCE_CHARS + 1)],
    ids=["invalid-utf8", "nul-byte", "oversized"],
)
async def test_unavailable_diff_does_not_prevent_overwriting(tmp_path, original):
    path = tmp_path / "note.txt"
    path.write_bytes(original)
    result = await RestrictedWriteTextFileTool(
        root_directory=tmp_path, allow_overwrite=True
    ).execute({"path": "note.txt", "content": "new"})
    assert path.read_bytes() == b"new"
    assert result["diff"] is None
    assert result["diff_unavailable_reason"]


@pytest.mark.asyncio
async def test_long_diff_is_bounded_and_truncation_is_explicit(tmp_path):
    content = "\n".join(str(index) * 40 for index in range(200)) + "\n"
    result = await RestrictedWriteTextFileTool(root_directory=tmp_path).execute(
        {"path": "note.txt", "content": content}
    )
    assert (tmp_path / "note.txt").read_text(encoding="utf-8") == content
    assert len(result["diff"]) <= MAX_DIFF_CHARS
    assert result["diff"].endswith("\n")
    assert result["diff_truncated"] is True


@pytest.mark.asyncio
@pytest.mark.skipif(os.name == "nt", reason="Windows filenames cannot contain newlines")
async def test_diff_quotes_filename_newlines(tmp_path):
    result = await RestrictedWriteTextFileTool(root_directory=tmp_path).execute(
        {"path": "note\n@@ -2 +2 @@.txt", "content": "hello"}
    )
    assert result["diff"].splitlines()[1] == '+++ b/"note\\n@@ -2 +2 @@.txt"'
