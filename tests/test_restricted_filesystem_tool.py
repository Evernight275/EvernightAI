import pytest

from EvernightAI.core.domain.tool import ToolManager, ToolRegister
from EvernightAI.core.error.tool import (
    ToolExecutionError,
    ToolInputError,
    ToolPolicyError,
)
from EvernightAI.core.schema.tool import ToolCall
from EvernightAI.infra.adapters.tool.restricted_filesystem import (
    RestrictedAppendTextFileTool,
    RestrictedApplyTextPatchTool,
    RestrictedCopyPathTool,
    RestrictedDeletePathTool,
    RestrictedFileHashTool,
    RestrictedFindPathsTool,
    RestrictedListDirectoryTool,
    RestrictedMakeDirectoryTool,
    RestrictedMovePathTool,
    RestrictedPathInfoTool,
    RestrictedReadJsonFileTool,
    RestrictedReadTextFileLinesTool,
    RestrictedReadTextFileTool,
    RestrictedSearchTextFilesTool,
    RestrictedWriteJsonFileTool,
    RestrictedWriteTextFileTool,
)
from EvernightAI.infra.registrations.tool.restricted_filesystem import (
    register_restricted_filesystem_tools,
)


@pytest.mark.asyncio
async def test_read_text_file_reads_inside_root_without_approval(tmp_path) -> None:
    (tmp_path / "note.txt").write_text("hello world", encoding="utf-8")
    register = ToolRegister()
    register_restricted_filesystem_tools(register, root_directory=tmp_path)
    manager = ToolManager(register)

    result = await manager.execute(
        ToolCall(
            tool_call_id="call-1",
            tool_call={
                "name": "read_text_file",
                "arguments": {"path": "note.txt"},
            },
        )
    )

    assert result.tool_call_result == {
        "path": "note.txt",
        "content": "hello world",
        "truncated": False,
    }


@pytest.mark.asyncio
async def test_read_text_file_truncates_content(tmp_path) -> None:
    (tmp_path / "note.txt").write_text("hello world", encoding="utf-8")
    register = ToolRegister()
    register_restricted_filesystem_tools(
        register,
        root_directory=tmp_path,
        max_read_chars=5,
    )
    manager = ToolManager(register)

    result = await manager.execute(
        ToolCall(
            tool_call_id="call-1",
            tool_call={
                "name": "read_text_file",
                "arguments": {"path": "note.txt"},
            },
        )
    )

    assert result.tool_call_result["content"] == "hello"
    assert result.tool_call_result["truncated"] is True


@pytest.mark.asyncio
async def test_read_text_file_rejects_paths_outside_root(tmp_path) -> None:
    secret = tmp_path.parent / "secret.txt"
    secret.write_text("secret", encoding="utf-8")
    register = ToolRegister()
    register_restricted_filesystem_tools(register, root_directory=tmp_path)
    manager = ToolManager(register)

    with pytest.raises(ToolExecutionError) as exc_info:
        await manager.execute(
            ToolCall(
                tool_call_id="call-1",
                tool_call={
                    "name": "read_text_file",
                    "arguments": {"path": "../secret.txt"},
                },
            )
        )

    assert isinstance(exc_info.value.cause, ToolInputError)


@pytest.mark.asyncio
async def test_write_text_file_requires_approval(tmp_path) -> None:
    register = ToolRegister()
    register_restricted_filesystem_tools(register, root_directory=tmp_path)
    manager = ToolManager(register)

    with pytest.raises(ToolPolicyError) as exc_info:
        await manager.execute(
            ToolCall(
                tool_call_id="call-1",
                tool_call={
                    "name": "write_text_file",
                    "arguments": {"path": "note.txt", "content": "hello"},
                },
            )
        )

    assert exc_info.value.detail == "Tool call requires approval"


@pytest.mark.asyncio
async def test_write_text_file_writes_inside_root_when_approved(tmp_path) -> None:
    register = ToolRegister()
    register_restricted_filesystem_tools(register, root_directory=tmp_path)
    manager = ToolManager(register)

    result = await manager.execute(
        ToolCall(
            tool_call_id="call-1",
            tool_call={
                "name": "write_text_file",
                "arguments": {"path": "nested/note.txt", "content": "hello"},
            },
            metadata={"approved": True},
        )
    )

    assert (tmp_path / "nested" / "note.txt").read_text(encoding="utf-8") == "hello"
    assert result.tool_call_result == {
        "path": "nested/note.txt",
        "bytes_written": 5,
        "overwritten": False,
    }


@pytest.mark.asyncio
async def test_write_text_file_rejects_overwrite_by_default(tmp_path) -> None:
    (tmp_path / "note.txt").write_text("old", encoding="utf-8")
    register = ToolRegister()
    register_restricted_filesystem_tools(register, root_directory=tmp_path)
    manager = ToolManager(register)

    with pytest.raises(ToolExecutionError) as exc_info:
        await manager.execute(
            ToolCall(
                tool_call_id="call-1",
                tool_call={
                    "name": "write_text_file",
                    "arguments": {"path": "note.txt", "content": "new"},
                },
                metadata={"approved": True},
            )
        )

    assert isinstance(exc_info.value.cause, ToolInputError)
    assert (tmp_path / "note.txt").read_text(encoding="utf-8") == "old"


@pytest.mark.asyncio
async def test_write_text_file_can_overwrite_when_enabled(tmp_path) -> None:
    (tmp_path / "note.txt").write_text("old", encoding="utf-8")
    register = ToolRegister()
    register_restricted_filesystem_tools(
        register,
        root_directory=tmp_path,
        allow_overwrite=True,
    )
    manager = ToolManager(register)

    result = await manager.execute(
        ToolCall(
            tool_call_id="call-1",
            tool_call={
                "name": "write_text_file",
                "arguments": {"path": "note.txt", "content": "new"},
            },
            metadata={"approved": True},
        )
    )

    assert (tmp_path / "note.txt").read_text(encoding="utf-8") == "new"
    assert result.tool_call_result["overwritten"] is True


@pytest.mark.asyncio
async def test_list_directory_lists_entries_inside_root_without_approval(tmp_path) -> None:
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "b").mkdir()
    register = ToolRegister()
    register_restricted_filesystem_tools(register, root_directory=tmp_path)
    manager = ToolManager(register)

    result = await manager.execute(
        ToolCall(
            tool_call_id="call-1",
            tool_call={
                "name": "list_directory",
                "arguments": {"path": "."},
            },
        )
    )

    assert result.tool_call_result == {
        "path": ".",
        "entries": [
            {"name": "a.txt", "path": "a.txt", "type": "file"},
            {"name": "b", "path": "b", "type": "directory"},
        ],
        "truncated": False,
    }


@pytest.mark.asyncio
async def test_list_directory_limits_entries(tmp_path) -> None:
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    register = ToolRegister()
    register_restricted_filesystem_tools(
        register,
        root_directory=tmp_path,
        max_directory_entries=1,
    )
    manager = ToolManager(register)

    result = await manager.execute(
        ToolCall(
            tool_call_id="call-1",
            tool_call={
                "name": "list_directory",
                "arguments": {"path": "."},
            },
        )
    )

    assert result.tool_call_result["entries"] == [
        {"name": "a.txt", "path": "a.txt", "type": "file"}
    ]
    assert result.tool_call_result["truncated"] is True


@pytest.mark.asyncio
async def test_search_text_files_finds_matching_lines(tmp_path) -> None:
    (tmp_path / "a.txt").write_text("hello\nworld\n", encoding="utf-8")
    (tmp_path / "b.md").write_text("hello docs\n", encoding="utf-8")
    register = ToolRegister()
    register_restricted_filesystem_tools(register, root_directory=tmp_path)
    manager = ToolManager(register)

    result = await manager.execute(
        ToolCall(
            tool_call_id="call-1",
            tool_call={
                "name": "search_text_files",
                "arguments": {"query": "hello", "pattern": "*.txt"},
            },
        )
    )

    assert result.tool_call_result["matches"] == [
        {"path": "a.txt", "line_number": 1, "line": "hello"}
    ]
    assert result.tool_call_result["truncated"] is False


@pytest.mark.asyncio
async def test_move_path_moves_file_when_approved(tmp_path) -> None:
    (tmp_path / "old.txt").write_text("hello", encoding="utf-8")
    register = ToolRegister()
    register_restricted_filesystem_tools(register, root_directory=tmp_path)
    manager = ToolManager(register)

    result = await manager.execute(
        ToolCall(
            tool_call_id="call-1",
            tool_call={
                "name": "move_path",
                "arguments": {
                    "source_path": "old.txt",
                    "destination_path": "nested/new.txt",
                },
            },
            metadata={"approved": True},
        )
    )

    assert not (tmp_path / "old.txt").exists()
    assert (tmp_path / "nested" / "new.txt").read_text(encoding="utf-8") == "hello"
    assert result.tool_call_result["destination_path"] == "nested/new.txt"


@pytest.mark.asyncio
async def test_delete_path_deletes_file_when_approved(tmp_path) -> None:
    (tmp_path / "note.txt").write_text("hello", encoding="utf-8")
    register = ToolRegister()
    register_restricted_filesystem_tools(register, root_directory=tmp_path)
    manager = ToolManager(register)

    result = await manager.execute(
        ToolCall(
            tool_call_id="call-1",
            tool_call={
                "name": "delete_path",
                "arguments": {"path": "note.txt"},
            },
            metadata={"approved": True},
        )
    )

    assert not (tmp_path / "note.txt").exists()
    assert result.tool_call_result == {
        "path": "note.txt",
        "type": "file",
        "deleted": True,
    }


@pytest.mark.asyncio
async def test_apply_text_patch_replaces_one_match_when_approved(tmp_path) -> None:
    (tmp_path / "note.txt").write_text("hello hello", encoding="utf-8")
    register = ToolRegister()
    register_restricted_filesystem_tools(register, root_directory=tmp_path)
    manager = ToolManager(register)

    result = await manager.execute(
        ToolCall(
            tool_call_id="call-1",
            tool_call={
                "name": "apply_text_patch",
                "arguments": {
                    "path": "note.txt",
                    "old_text": "hello",
                    "new_text": "hi",
                },
            },
            metadata={"approved": True},
        )
    )

    assert (tmp_path / "note.txt").read_text(encoding="utf-8") == "hi hello"
    assert result.tool_call_result["replacements"] == 1


@pytest.mark.asyncio
async def test_path_info_returns_file_metadata(tmp_path) -> None:
    (tmp_path / "note.txt").write_text("hello", encoding="utf-8")
    register = ToolRegister()
    register_restricted_filesystem_tools(register, root_directory=tmp_path)
    manager = ToolManager(register)

    result = await manager.execute(
        ToolCall(
            tool_call_id="call-1",
            tool_call={
                "name": "path_info",
                "arguments": {"path": "note.txt"},
            },
        )
    )

    assert result.tool_call_result["path"] == "note.txt"
    assert result.tool_call_result["type"] == "file"
    assert result.tool_call_result["size_bytes"] == 5


@pytest.mark.asyncio
async def test_make_directory_creates_nested_directory_when_approved(tmp_path) -> None:
    register = ToolRegister()
    register_restricted_filesystem_tools(register, root_directory=tmp_path)
    manager = ToolManager(register)

    result = await manager.execute(
        ToolCall(
            tool_call_id="call-1",
            tool_call={
                "name": "make_directory",
                "arguments": {"path": "a/b"},
            },
            metadata={"approved": True},
        )
    )

    assert (tmp_path / "a" / "b").is_dir()
    assert result.tool_call_result["created"] is True


@pytest.mark.asyncio
async def test_copy_path_copies_file_when_approved(tmp_path) -> None:
    (tmp_path / "source.txt").write_text("hello", encoding="utf-8")
    register = ToolRegister()
    register_restricted_filesystem_tools(register, root_directory=tmp_path)
    manager = ToolManager(register)

    result = await manager.execute(
        ToolCall(
            tool_call_id="call-1",
            tool_call={
                "name": "copy_path",
                "arguments": {
                    "source_path": "source.txt",
                    "destination_path": "copies/source.txt",
                },
            },
            metadata={"approved": True},
        )
    )

    assert (tmp_path / "source.txt").exists()
    assert (tmp_path / "copies" / "source.txt").read_text(encoding="utf-8") == "hello"
    assert result.tool_call_result["type"] == "file"


@pytest.mark.asyncio
async def test_json_file_tools_read_and_write_json_when_approved(tmp_path) -> None:
    register = ToolRegister()
    register_restricted_filesystem_tools(register, root_directory=tmp_path)
    manager = ToolManager(register)

    write_result = await manager.execute(
        ToolCall(
            tool_call_id="call-1",
            tool_call={
                "name": "write_json_file",
                "arguments": {
                    "path": "data/item.json",
                    "data": {"name": "Evernight", "enabled": True},
                },
            },
            metadata={"approved": True},
        )
    )
    read_result = await manager.execute(
        ToolCall(
            tool_call_id="call-2",
            tool_call={
                "name": "read_json_file",
                "arguments": {"path": "data/item.json"},
            },
        )
    )

    assert write_result.tool_call_result["path"] == "data/item.json"
    assert read_result.tool_call_result["data"] == {
        "name": "Evernight",
        "enabled": True,
    }


@pytest.mark.asyncio
async def test_append_text_file_appends_when_approved(tmp_path) -> None:
    (tmp_path / "note.txt").write_text("hello", encoding="utf-8")
    register = ToolRegister()
    register_restricted_filesystem_tools(register, root_directory=tmp_path)
    manager = ToolManager(register)

    result = await manager.execute(
        ToolCall(
            tool_call_id="call-1",
            tool_call={
                "name": "append_text_file",
                "arguments": {"path": "note.txt", "content": " world"},
            },
            metadata={"approved": True},
        )
    )

    assert (tmp_path / "note.txt").read_text(encoding="utf-8") == "hello world"
    assert result.tool_call_result["created"] is False
    assert result.tool_call_result["bytes_written"] == 6


@pytest.mark.asyncio
async def test_find_paths_finds_matching_files(tmp_path) -> None:
    (tmp_path / "a.py").write_text("print('a')", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    register = ToolRegister()
    register_restricted_filesystem_tools(register, root_directory=tmp_path)
    manager = ToolManager(register)

    result = await manager.execute(
        ToolCall(
            tool_call_id="call-1",
            tool_call={
                "name": "find_paths",
                "arguments": {"pattern": "*.py", "type": "file"},
            },
        )
    )

    assert result.tool_call_result["matches"] == [
        {"path": "a.py", "type": "file"}
    ]


@pytest.mark.asyncio
async def test_read_text_file_lines_returns_line_range(tmp_path) -> None:
    (tmp_path / "note.txt").write_text("one\ntwo\nthree\n", encoding="utf-8")
    register = ToolRegister()
    register_restricted_filesystem_tools(register, root_directory=tmp_path)
    manager = ToolManager(register)

    result = await manager.execute(
        ToolCall(
            tool_call_id="call-1",
            tool_call={
                "name": "read_text_file_lines",
                "arguments": {
                    "path": "note.txt",
                    "start_line": 2,
                    "line_count": 2,
                },
            },
        )
    )

    assert result.tool_call_result["lines"] == [
        {"line_number": 2, "text": "two"},
        {"line_number": 3, "text": "three"},
    ]


@pytest.mark.asyncio
async def test_file_hash_returns_sha256(tmp_path) -> None:
    (tmp_path / "note.txt").write_text("hello", encoding="utf-8")
    register = ToolRegister()
    register_restricted_filesystem_tools(register, root_directory=tmp_path)
    manager = ToolManager(register)

    result = await manager.execute(
        ToolCall(
            tool_call_id="call-1",
            tool_call={
                "name": "file_hash",
                "arguments": {"path": "note.txt"},
            },
        )
    )

    assert result.tool_call_result["algorithm"] == "sha256"
    assert result.tool_call_result["hexdigest"] == (
        "2cf24dba5fb0a30e26e83b2ac5b9e29e"
        "1b161e5c1fa7425e73043362938b9824"
    )


@pytest.mark.asyncio
async def test_filesystem_tools_reject_invalid_text_inputs(tmp_path) -> None:
    (tmp_path / "note.txt").write_text("hello", encoding="utf-8")

    with pytest.raises(ToolInputError, match="does not exist"):
        await RestrictedReadTextFileTool(root_directory=tmp_path).execute(
            {"path": "missing.txt"}
        )
    with pytest.raises(ToolInputError, match="content must be a string"):
        await RestrictedWriteTextFileTool(root_directory=tmp_path).execute(
            {"path": "note.txt", "content": 1}
        )
    with pytest.raises(ToolInputError, match="content must be a string"):
        await RestrictedAppendTextFileTool(root_directory=tmp_path).execute(
            {"path": "note.txt", "content": 1}
        )
    with pytest.raises(ToolInputError, match="create value must be a boolean"):
        await RestrictedAppendTextFileTool(root_directory=tmp_path).execute(
            {"path": "note.txt", "content": "x", "create": "yes"}
        )
    with pytest.raises(ToolInputError, match="does not exist"):
        await RestrictedAppendTextFileTool(root_directory=tmp_path).execute(
            {"path": "missing.txt", "content": "x", "create": False}
        )


@pytest.mark.asyncio
async def test_list_and_find_paths_reject_invalid_inputs_and_truncate(tmp_path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("a", encoding="utf-8")
    (tmp_path / "src" / "b.py").write_text("b", encoding="utf-8")
    (tmp_path / "src" / "pkg").mkdir()

    with pytest.raises(ToolInputError, match="directory .* does not exist"):
        await RestrictedListDirectoryTool(root_directory=tmp_path).execute(
            {"path": "missing"}
        )
    with pytest.raises(ToolInputError, match="directory .* does not exist"):
        await RestrictedFindPathsTool(root_directory=tmp_path).execute(
            {"path": "missing", "pattern": "*.py"}
        )
    with pytest.raises(ToolInputError, match="non-empty string"):
        await RestrictedFindPathsTool(root_directory=tmp_path).execute({"pattern": ""})
    with pytest.raises(ToolInputError, match="file, directory, or any"):
        await RestrictedFindPathsTool(root_directory=tmp_path).execute(
            {"pattern": "*", "type": "symlink"}
        )

    file_result = await RestrictedFindPathsTool(
        root_directory=tmp_path,
        max_results=1,
    ).execute({"path": "src", "pattern": "*.py", "type": "file"})
    directory_result = await RestrictedFindPathsTool(root_directory=tmp_path).execute(
        {"path": "src", "pattern": "*", "type": "directory"}
    )

    assert file_result["matches"] == [{"path": "src/a.py", "type": "file"}]
    assert file_result["truncated"] is True
    assert directory_result["matches"] == [
        {"path": "src/pkg", "type": "directory"}
    ]


@pytest.mark.asyncio
async def test_search_text_files_rejects_invalid_inputs_and_limits_results(tmp_path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.txt").write_text("Alpha\nalpha\n", encoding="utf-8")
    (tmp_path / "src" / "b.txt").write_text("alpha\n", encoding="utf-8")

    with pytest.raises(ToolInputError, match="directory .* does not exist"):
        await RestrictedSearchTextFilesTool(root_directory=tmp_path).execute(
            {"path": "missing", "query": "alpha"}
        )
    with pytest.raises(ToolInputError, match="query must be a non-empty string"):
        await RestrictedSearchTextFilesTool(root_directory=tmp_path).execute(
            {"query": ""}
        )
    with pytest.raises(ToolInputError, match="pattern must be a non-empty string"):
        await RestrictedSearchTextFilesTool(root_directory=tmp_path).execute(
            {"query": "alpha", "pattern": ""}
        )
    with pytest.raises(ToolInputError, match="case_sensitive value must be a boolean"):
        await RestrictedSearchTextFilesTool(root_directory=tmp_path).execute(
            {"query": "alpha", "case_sensitive": "no"}
        )

    result = await RestrictedSearchTextFilesTool(
        root_directory=tmp_path,
        max_results=2,
        max_file_chars=8,
    ).execute(
        {
            "path": "src",
            "query": "alpha",
            "pattern": "*.txt",
            "case_sensitive": False,
        }
    )

    assert result["matches"] == [
        {"path": "src/a.txt", "line_number": 1, "line": "Alpha"},
        {"path": "src/b.txt", "line_number": 1, "line": "alpha"},
    ]
    assert result["scanned_files"] == 2
    assert result["truncated"] is True

    (tmp_path / "src" / "c.txt").write_text("alpha\n", encoding="utf-8")
    limited_result = await RestrictedSearchTextFilesTool(
        root_directory=tmp_path,
        max_results=1,
    ).execute(
        {
            "path": "src",
            "query": "alpha",
            "pattern": "*.txt",
            "case_sensitive": False,
        }
    )

    assert limited_result["matches"] == [
        {"path": "src/a.txt", "line_number": 1, "line": "Alpha"}
    ]
    assert limited_result["truncated"] is True


@pytest.mark.asyncio
async def test_read_lines_rejects_invalid_file_and_range_inputs(tmp_path) -> None:
    (tmp_path / "note.txt").write_text("one\ntwo\nthree\n", encoding="utf-8")

    with pytest.raises(ToolInputError, match="does not exist"):
        await RestrictedReadTextFileLinesTool(root_directory=tmp_path).execute(
            {"path": "missing.txt"}
        )
    with pytest.raises(ToolInputError, match="start_line value"):
        await RestrictedReadTextFileLinesTool(root_directory=tmp_path).execute(
            {"path": "note.txt", "start_line": 0}
        )
    with pytest.raises(ToolInputError, match="line_count value"):
        await RestrictedReadTextFileLinesTool(root_directory=tmp_path).execute(
            {"path": "note.txt", "line_count": 0}
        )

    result = await RestrictedReadTextFileLinesTool(
        root_directory=tmp_path,
        max_lines=1,
    ).execute({"path": "note.txt", "start_line": 2, "line_count": 5})

    assert result["lines"] == [{"line_number": 2, "text": "two"}]
    assert result["truncated"] is True


@pytest.mark.asyncio
async def test_move_path_rejects_invalid_inputs_and_overwrites_when_enabled(tmp_path) -> None:
    (tmp_path / "source.txt").write_text("new", encoding="utf-8")
    (tmp_path / "target.txt").write_text("old", encoding="utf-8")
    (tmp_path / "target_dir").mkdir()
    (tmp_path / "target_dir" / "old.txt").write_text("old", encoding="utf-8")

    with pytest.raises(ToolInputError, match="does not exist"):
        await RestrictedMovePathTool(root_directory=tmp_path).execute(
            {"source_path": "missing.txt", "destination_path": "target.txt"}
        )
    with pytest.raises(ToolInputError, match="overwrite value must be a boolean"):
        await RestrictedMovePathTool(root_directory=tmp_path).execute(
            {
                "source_path": "source.txt",
                "destination_path": "target.txt",
                "overwrite": "yes",
            }
        )
    with pytest.raises(ToolInputError, match="not enabled"):
        await RestrictedMovePathTool(root_directory=tmp_path).execute(
            {
                "source_path": "source.txt",
                "destination_path": "target.txt",
                "overwrite": True,
            }
        )
    with pytest.raises(ToolInputError, match="destination .* exists"):
        await RestrictedMovePathTool(root_directory=tmp_path).execute(
            {"source_path": "source.txt", "destination_path": "target.txt"}
        )

    result = await RestrictedMovePathTool(
        root_directory=tmp_path,
        allow_overwrite=True,
    ).execute(
        {
            "source_path": "source.txt",
            "destination_path": "target_dir",
            "overwrite": True,
        }
    )

    assert result["overwritten"] is True
    assert (tmp_path / "target_dir").read_text(encoding="utf-8") == "new"

    (tmp_path / "source2.txt").write_text("newer", encoding="utf-8")
    (tmp_path / "target2.txt").write_text("older", encoding="utf-8")
    file_result = await RestrictedMovePathTool(
        root_directory=tmp_path,
        allow_overwrite=True,
    ).execute(
        {
            "source_path": "source2.txt",
            "destination_path": "target2.txt",
            "overwrite": True,
        }
    )

    assert file_result["overwritten"] is True
    assert (tmp_path / "target2.txt").read_text(encoding="utf-8") == "newer"


@pytest.mark.asyncio
async def test_delete_path_rejects_invalid_inputs_and_deletes_directory(tmp_path) -> None:
    (tmp_path / "dir").mkdir()
    (tmp_path / "dir" / "note.txt").write_text("hello", encoding="utf-8")

    with pytest.raises(ToolInputError, match="recursive value must be a boolean"):
        await RestrictedDeletePathTool(root_directory=tmp_path).execute(
            {"path": "dir", "recursive": "yes"}
        )
    with pytest.raises(ToolInputError, match="does not exist"):
        await RestrictedDeletePathTool(root_directory=tmp_path).execute(
            {"path": "missing"}
        )
    with pytest.raises(ToolInputError, match="requires recursive=true"):
        await RestrictedDeletePathTool(root_directory=tmp_path).execute({"path": "dir"})

    result = await RestrictedDeletePathTool(root_directory=tmp_path).execute(
        {"path": "dir", "recursive": True}
    )

    assert result == {"path": "dir", "type": "directory", "deleted": True}
    assert not (tmp_path / "dir").exists()


@pytest.mark.asyncio
async def test_apply_patch_rejects_invalid_inputs_and_replaces_all(tmp_path) -> None:
    (tmp_path / "note.txt").write_text("hello hello", encoding="utf-8")
    tool = RestrictedApplyTextPatchTool(root_directory=tmp_path)

    with pytest.raises(ToolInputError, match="does not exist"):
        await tool.execute({"path": "missing.txt", "old_text": "x", "new_text": "y"})
    with pytest.raises(ToolInputError, match="old_text value"):
        await tool.execute({"path": "note.txt", "old_text": "", "new_text": "y"})
    with pytest.raises(ToolInputError, match="new_text value"):
        await tool.execute({"path": "note.txt", "old_text": "hello", "new_text": 1})
    with pytest.raises(ToolInputError, match="replace_all value"):
        await tool.execute(
            {
                "path": "note.txt",
                "old_text": "hello",
                "new_text": "hi",
                "replace_all": "yes",
            }
        )
    with pytest.raises(ToolInputError, match="not found"):
        await tool.execute({"path": "note.txt", "old_text": "missing", "new_text": "hi"})

    result = await tool.execute(
        {
            "path": "note.txt",
            "old_text": "hello",
            "new_text": "hi",
            "replace_all": True,
        }
    )

    assert (tmp_path / "note.txt").read_text(encoding="utf-8") == "hi hi"
    assert result["replacements"] == 2


@pytest.mark.asyncio
async def test_hash_and_path_info_reject_invalid_inputs(tmp_path) -> None:
    (tmp_path / "note.txt").write_text("hello", encoding="utf-8")

    with pytest.raises(ToolInputError, match="does not exist"):
        await RestrictedFileHashTool(root_directory=tmp_path).execute(
            {"path": "missing.txt"}
        )
    with pytest.raises(ToolInputError, match="algorithm must be"):
        await RestrictedFileHashTool(root_directory=tmp_path).execute(
            {"path": "note.txt", "algorithm": "blake3"}
        )
    with pytest.raises(ToolInputError, match="does not exist"):
        await RestrictedPathInfoTool(root_directory=tmp_path).execute(
            {"path": "missing.txt"}
        )

    (tmp_path / "dir").mkdir()
    result = await RestrictedPathInfoTool(root_directory=tmp_path).execute(
        {"path": "dir"}
    )
    assert result["type"] == "directory"


@pytest.mark.asyncio
async def test_make_directory_rejects_invalid_options_and_reports_existing(tmp_path) -> None:
    (tmp_path / "existing").mkdir()

    with pytest.raises(ToolInputError, match="parents value must be a boolean"):
        await RestrictedMakeDirectoryTool(root_directory=tmp_path).execute(
            {"path": "new", "parents": "yes"}
        )
    with pytest.raises(ToolInputError, match="exist_ok value must be a boolean"):
        await RestrictedMakeDirectoryTool(root_directory=tmp_path).execute(
            {"path": "new", "exist_ok": "yes"}
        )

    result = await RestrictedMakeDirectoryTool(root_directory=tmp_path).execute(
        {"path": "existing"}
    )
    assert result["created"] is False
    assert result["existed"] is True


@pytest.mark.asyncio
async def test_copy_path_rejects_invalid_inputs_and_overwrites_files_and_directories(
    tmp_path,
) -> None:
    (tmp_path / "source.txt").write_text("new", encoding="utf-8")
    (tmp_path / "target.txt").write_text("old", encoding="utf-8")
    (tmp_path / "source_dir").mkdir()
    (tmp_path / "source_dir" / "new.txt").write_text("new", encoding="utf-8")
    (tmp_path / "target_dir").mkdir()
    (tmp_path / "target_dir" / "old.txt").write_text("old", encoding="utf-8")

    with pytest.raises(ToolInputError, match="does not exist"):
        await RestrictedCopyPathTool(root_directory=tmp_path).execute(
            {"source_path": "missing.txt", "destination_path": "target.txt"}
        )
    with pytest.raises(ToolInputError, match="overwrite value must be a boolean"):
        await RestrictedCopyPathTool(root_directory=tmp_path).execute(
            {
                "source_path": "source.txt",
                "destination_path": "target.txt",
                "overwrite": "yes",
            }
        )
    with pytest.raises(ToolInputError, match="not enabled"):
        await RestrictedCopyPathTool(root_directory=tmp_path).execute(
            {
                "source_path": "source.txt",
                "destination_path": "target.txt",
                "overwrite": True,
            }
        )
    with pytest.raises(ToolInputError, match="destination .* exists"):
        await RestrictedCopyPathTool(root_directory=tmp_path).execute(
            {"source_path": "source.txt", "destination_path": "target.txt"}
        )

    file_result = await RestrictedCopyPathTool(
        root_directory=tmp_path,
        allow_overwrite=True,
    ).execute(
        {
            "source_path": "source.txt",
            "destination_path": "target.txt",
            "overwrite": True,
        }
    )
    dir_result = await RestrictedCopyPathTool(
        root_directory=tmp_path,
        allow_overwrite=True,
    ).execute(
        {
            "source_path": "source_dir",
            "destination_path": "target_dir",
            "overwrite": True,
        }
    )

    assert file_result["type"] == "file"
    assert file_result["overwritten"] is True
    assert (tmp_path / "target.txt").read_text(encoding="utf-8") == "new"
    assert dir_result["type"] == "directory"
    assert dir_result["overwritten"] is True
    assert (tmp_path / "target_dir" / "new.txt").read_text(encoding="utf-8") == "new"


@pytest.mark.asyncio
async def test_json_tools_reject_invalid_inputs_and_overwrite_when_enabled(tmp_path) -> None:
    (tmp_path / "invalid.json").write_text("{", encoding="utf-8")
    (tmp_path / "data.json").write_text('{"old": true}', encoding="utf-8")

    with pytest.raises(ToolInputError, match="does not exist"):
        await RestrictedReadJsonFileTool(root_directory=tmp_path).execute(
            {"path": "missing.json"}
        )
    with pytest.raises(ToolInputError, match="not valid JSON"):
        await RestrictedReadJsonFileTool(root_directory=tmp_path).execute(
            {"path": "invalid.json"}
        )
    with pytest.raises(ToolInputError, match="indent value must be an integer"):
        await RestrictedWriteJsonFileTool(root_directory=tmp_path).execute(
            {"path": "data.json", "data": {}, "indent": "2"}
        )
    with pytest.raises(ToolInputError, match="already exists"):
        await RestrictedWriteJsonFileTool(root_directory=tmp_path).execute(
            {"path": "data.json", "data": {}}
        )
    with pytest.raises(ToolInputError, match="JSON serializable"):
        await RestrictedWriteJsonFileTool(root_directory=tmp_path).execute(
            {"path": "new.json", "data": object()}
        )

    result = await RestrictedWriteJsonFileTool(
        root_directory=tmp_path,
        allow_overwrite=True,
    ).execute({"path": "data.json", "data": {"new": True}, "indent": 0})

    assert result["overwritten"] is True
    assert (tmp_path / "data.json").read_text(encoding="utf-8") == '{\n"new": true\n}\n'


@pytest.mark.asyncio
async def test_resolve_path_rejects_missing_and_escaping_paths(tmp_path) -> None:
    with pytest.raises(ToolInputError, match="non-empty string"):
        await RestrictedPathInfoTool(root_directory=tmp_path).execute({"path": ""})
    with pytest.raises(ToolInputError, match="inside the root"):
        await RestrictedPathInfoTool(root_directory=tmp_path).execute({"path": ".."})
