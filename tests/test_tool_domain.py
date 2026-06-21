import pytest

from EvernightAI.core.domain.tool import BasicToolSafetyPolicy, ToolManager, ToolRegister
from EvernightAI.core.error.tool import (
    ToolExecutionError,
    ToolInputError,
    ToolNotFoundError,
    ToolPolicyError,
)
from EvernightAI.core.schema.tool import (
    ToolApprovalDecision,
    ToolApprovalStatus,
    ToolCall,
    ToolDefinition,
    ToolPermission,
    ToolSafetyLevel,
)


def make_tool() -> ToolDefinition:
    return ToolDefinition(
        name="add",
        description="Add two numbers",
        parameters_schema={
            "type": "object",
            "properties": {
                "left": {"type": "number"},
                "right": {"type": "number"},
            },
            "required": ["left", "right"],
        },
    )


@pytest.mark.asyncio
async def test_tool_manager_executes_registered_tool() -> None:
    async def add(arguments: dict[str, object]) -> dict[str, object]:
        left = arguments["left"]
        right = arguments["right"]
        assert isinstance(left, int | float)
        assert isinstance(right, int | float)
        return {"result": left + right}

    register = ToolRegister()
    register.register(make_tool(), add)
    manager = ToolManager(register)

    result = await manager.execute(
        ToolCall(
            tool_call_id="call-1",
            tool_call={"name": "add", "arguments": {"left": 1, "right": 2}},
        )
    )

    assert manager.list_tools() == [make_tool()]
    assert result.tool_call_id == "call-1"
    assert result.tool_call_result == {"result": 3}
    assert result.metadata == {}


def test_tool_register_raises_for_missing_tool() -> None:
    register = ToolRegister()

    with pytest.raises(ToolNotFoundError):
        register.get("missing")


@pytest.mark.asyncio
async def test_tool_manager_rejects_invalid_call_arguments() -> None:
    manager = ToolManager(ToolRegister())

    with pytest.raises(ToolInputError):
        await manager.execute(
            ToolCall(
                tool_call_id="call-1",
                tool_call={"name": "add", "arguments": ["not", "a", "dict"]},
            )
        )


@pytest.mark.asyncio
async def test_tool_manager_wraps_executor_errors() -> None:
    async def broken(arguments: dict[str, object]) -> dict[str, object]:
        raise RuntimeError("boom")

    register = ToolRegister()
    register.register(make_tool(), broken)
    manager = ToolManager(register)

    with pytest.raises(ToolExecutionError) as exc_info:
        await manager.execute(
            ToolCall(
                tool_call_id="call-1",
                tool_call={"name": "add", "arguments": {}},
            )
        )

    assert isinstance(exc_info.value.cause, RuntimeError)


@pytest.mark.asyncio
async def test_tool_manager_rejects_tool_calls_that_require_approval() -> None:
    async def write(arguments: dict[str, object]) -> dict[str, object]:
        return {"ok": True}

    register = ToolRegister()
    register.register(
        ToolDefinition(
            name="write_file",
            description="Write a file",
            permissions=[ToolPermission.FILESYSTEM, ToolPermission.WRITE],
            safety_level=ToolSafetyLevel.SENSITIVE,
        ),
        write,
    )
    manager = ToolManager(register)

    with pytest.raises(ToolPolicyError) as exc_info:
        await manager.execute(
            ToolCall(
                tool_call_id="call-1",
                tool_call={"name": "write_file", "arguments": {}},
            )
        )

    assert exc_info.value.detail == "Tool call requires approval"


def test_tool_safety_policy_returns_approval_request() -> None:
    policy = BasicToolSafetyPolicy()
    tool = ToolDefinition(
        name="write_file",
        description="Write a file",
        permissions=[ToolPermission.FILESYSTEM, ToolPermission.WRITE],
        safety_level=ToolSafetyLevel.SENSITIVE,
    )
    call = ToolCall(
        tool_call_id="call-1",
        tool_call={"name": "write_file", "arguments": {"path": "note.txt"}},
    )

    decision = policy.authorize(tool, call)

    assert decision.allowed is False
    assert decision.requires_approval is True
    assert decision.approval_request is not None
    assert decision.approval_request.approval_id == "call-1:approval"
    assert decision.approval_request.tool_name == "write_file"
    assert decision.approval_request.permissions == [
        ToolPermission.FILESYSTEM,
        ToolPermission.WRITE,
    ]


def test_tool_safety_policy_allows_safe_filesystem_read() -> None:
    policy = BasicToolSafetyPolicy()
    tool = ToolDefinition(
        name="read_file",
        description="Read a file",
        permissions=[ToolPermission.READ, ToolPermission.FILESYSTEM],
        safety_level=ToolSafetyLevel.SAFE,
    )
    call = ToolCall(
        tool_call_id="call-1",
        tool_call={"name": "read_file", "arguments": {"path": "note.txt"}},
    )

    decision = policy.authorize(tool, call)

    assert decision.allowed is True
    assert decision.requires_approval is False
    assert decision.approval_request is None


@pytest.mark.asyncio
async def test_tool_manager_executes_approved_sensitive_tool_call() -> None:
    async def write(arguments: dict[str, object]) -> dict[str, object]:
        return {"ok": True}

    register = ToolRegister()
    register.register(
        ToolDefinition(
            name="write_file",
            description="Write a file",
            permissions=[ToolPermission.FILESYSTEM, ToolPermission.WRITE],
            safety_level=ToolSafetyLevel.SENSITIVE,
        ),
        write,
    )
    manager = ToolManager(register)

    result = await manager.execute(
        ToolCall(
            tool_call_id="call-1",
            tool_call={"name": "write_file", "arguments": {}},
            metadata={"approved": True},
        )
    )

    assert result.tool_call_result == {"ok": True}


@pytest.mark.asyncio
async def test_tool_manager_executes_with_approval_decision() -> None:
    async def write(arguments: dict[str, object]) -> dict[str, object]:
        return {"ok": True}

    register = ToolRegister()
    register.register(
        ToolDefinition(
            name="write_file",
            description="Write a file",
            permissions=[ToolPermission.FILESYSTEM, ToolPermission.WRITE],
            safety_level=ToolSafetyLevel.SENSITIVE,
        ),
        write,
    )
    manager = ToolManager(register)

    result = await manager.execute(
        ToolCall(
            tool_call_id="call-1",
            tool_call={"name": "write_file", "arguments": {}},
            approval=ToolApprovalDecision(
                approval_id="call-1:approval",
                tool_call_id="call-1",
                status=ToolApprovalStatus.APPROVED,
            ),
        )
    )

    assert result.tool_call_result == {"ok": True}


@pytest.mark.asyncio
async def test_tool_manager_rejects_denied_approval_decision() -> None:
    async def write(arguments: dict[str, object]) -> dict[str, object]:
        return {"ok": True}

    register = ToolRegister()
    register.register(
        ToolDefinition(
            name="write_file",
            description="Write a file",
            permissions=[ToolPermission.FILESYSTEM, ToolPermission.WRITE],
            safety_level=ToolSafetyLevel.SENSITIVE,
        ),
        write,
    )
    manager = ToolManager(register)

    with pytest.raises(ToolPolicyError) as exc_info:
        await manager.execute(
            ToolCall(
                tool_call_id="call-1",
                tool_call={"name": "write_file", "arguments": {}},
                approval=ToolApprovalDecision(
                    approval_id="call-1:approval",
                    tool_call_id="call-1",
                    status=ToolApprovalStatus.DENIED,
                    reason="User denied",
                ),
            )
        )

    assert exc_info.value.detail == "User denied"


@pytest.mark.asyncio
async def test_tool_manager_blocks_restricted_permissions() -> None:
    async def shell(arguments: dict[str, object]) -> dict[str, object]:
        return {"ok": True}

    register = ToolRegister()
    register.register(
        ToolDefinition(
            name="run_shell",
            description="Run a shell command",
            permissions=[ToolPermission.SHELL],
            safety_level=ToolSafetyLevel.RESTRICTED,
        ),
        shell,
    )
    manager = ToolManager(register, BasicToolSafetyPolicy())

    with pytest.raises(ToolPolicyError) as exc_info:
        await manager.execute(
            ToolCall(
                tool_call_id="call-1",
                tool_call={"name": "run_shell", "arguments": {}},
                metadata={"approved": True},
            )
        )

    assert exc_info.value.detail == "Blocked permissions: shell"
