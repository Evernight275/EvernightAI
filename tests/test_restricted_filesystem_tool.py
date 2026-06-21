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
