import pytest

from EvernightAI.core.domain.tool import ToolManager, ToolRegister
from EvernightAI.core.error.tool import (
    ToolExecutionError,
    ToolInputError,
    ToolPolicyError,
)
from EvernightAI.core.schema.tool import ToolCall
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
