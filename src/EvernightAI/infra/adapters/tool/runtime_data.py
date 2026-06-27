from typing import Any
from uuid import uuid4

from EvernightAI.core.error.tool import ToolInputError
from EvernightAI.core.protocol.context import ContextManageProtocol
from EvernightAI.core.protocol.memory import MemoryManageProtocol
from EvernightAI.core.protocol.session import SessionManageProtocol
from EvernightAI.core.protocol.tool import ToolExecutorProtocol
from EvernightAI.core.schema.content import (
    Content,
    ContentPart,
    ContentPartType,
    MessageRole,
)
from EvernightAI.core.schema.context import Context
from EvernightAI.core.schema.memory import MemoryItem, MemoryKind, MemoryScope
from EvernightAI.core.schema.session import Session
from EvernightAI.core.schema.tool import (
    ToolDefinition,
    ToolPermission,
    ToolSafetyLevel,
)


class CreateContextTool:
    def __init__(self, contexts: ContextManageProtocol) -> None:
        self._contexts = contexts

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="create_context",
            description="Create a runtime context",
            parameters_schema={
                "type": "object",
                "properties": {
                    "context_id": {"type": "string"},
                    "metadata": {"type": "object"},
                },
            },
            permissions=[ToolPermission.WRITE, ToolPermission.DATABASE],
            safety_level=ToolSafetyLevel.SENSITIVE,
            requires_approval=True,
        )

    def executor(self) -> ToolExecutorProtocol:
        return self.execute

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        context_id = _optional_string(arguments.get("context_id")) or (
            f"context-{uuid4().hex}"
        )
        metadata = _metadata(arguments.get("metadata"))
        context = await self._contexts.create(
            Context(context_id=context_id, metadata=metadata)
        )
        return context.model_dump(mode="json")


class ListContextsTool:
    def __init__(self, contexts: ContextManageProtocol) -> None:
        self._contexts = contexts

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="list_contexts",
            description="List runtime contexts",
            parameters_schema={"type": "object", "properties": {}},
            permissions=[ToolPermission.READ, ToolPermission.DATABASE],
            safety_level=ToolSafetyLevel.SAFE,
        )

    def executor(self) -> ToolExecutorProtocol:
        return self.execute

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        contexts = await self._contexts.list_contexts()
        return {
            "contexts": [
                context.model_dump(mode="json")
                for context in contexts
            ],
        }


class GetContextTool:
    def __init__(self, contexts: ContextManageProtocol) -> None:
        self._contexts = contexts

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="get_context",
            description="Get a runtime context",
            parameters_schema={
                "type": "object",
                "properties": {"context_id": {"type": "string"}},
                "required": ["context_id"],
            },
            permissions=[ToolPermission.READ, ToolPermission.DATABASE],
            safety_level=ToolSafetyLevel.SAFE,
        )

    def executor(self) -> ToolExecutorProtocol:
        return self.execute

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        context_id = _required_string(arguments.get("context_id"), "context_id")
        context = await self._contexts.get(context_id)
        return context.model_dump(mode="json")


class AppendContextMessageTool:
    def __init__(self, contexts: ContextManageProtocol) -> None:
        self._contexts = contexts

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="append_context_message",
            description="Append a text message to a runtime context",
            parameters_schema={
                "type": "object",
                "properties": {
                    "context_id": {"type": "string"},
                    "role": {"type": "string"},
                    "text": {"type": "string"},
                    "metadata": {"type": "object"},
                },
                "required": ["context_id", "role", "text"],
            },
            permissions=[ToolPermission.WRITE, ToolPermission.DATABASE],
            safety_level=ToolSafetyLevel.SENSITIVE,
            requires_approval=True,
        )

    def executor(self) -> ToolExecutorProtocol:
        return self.execute

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        context_id = _required_string(arguments.get("context_id"), "context_id")
        role = _message_role(arguments.get("role"))
        text = _required_string(arguments.get("text"), "text")
        metadata = _metadata(arguments.get("metadata"))
        context = await self._contexts.append(
            context_id,
            Content(
                role=role,
                content=[
                    ContentPart(
                        type=ContentPartType.TEXT,
                        text=text,
                    )
                ],
                metadata=metadata,
            ),
        )
        return context.model_dump(mode="json")


class WriteMemoryTool:
    def __init__(self, memories: MemoryManageProtocol) -> None:
        self._memories = memories

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="write_memory",
            description="Write a durable memory item",
            parameters_schema={
                "type": "object",
                "properties": {
                    "memory_id": {"type": "string"},
                    "content": {"type": "string"},
                    "kind": {"type": "string"},
                    "scope": {"type": "string"},
                    "scope_id": {"type": "string"},
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "priority": {"type": "integer"},
                    "metadata": {"type": "object"},
                },
                "required": ["content"],
            },
            permissions=[ToolPermission.WRITE, ToolPermission.DATABASE],
            safety_level=ToolSafetyLevel.SENSITIVE,
            requires_approval=True,
        )

    def executor(self) -> ToolExecutorProtocol:
        return self.execute

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        memory_id = _optional_string(arguments.get("memory_id")) or (
            f"memory-{uuid4().hex}"
        )
        content = _required_string(arguments.get("content"), "content")
        memory = MemoryItem(
            memory_id=memory_id,
            content=content,
            kind=_memory_kind(arguments.get("kind")),
            scope=_memory_scope(arguments.get("scope")),
            scope_id=_optional_string(arguments.get("scope_id")),
            tags=_string_list(arguments.get("tags")),
            priority=_int(arguments.get("priority"), 0),
            metadata=_metadata(arguments.get("metadata")),
        )
        created = await self._memories.create(memory)
        return created.model_dump(mode="json")


class ListMemoriesTool:
    def __init__(self, memories: MemoryManageProtocol) -> None:
        self._memories = memories

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="list_memories",
            description="List runtime memories",
            parameters_schema={"type": "object", "properties": {}},
            permissions=[ToolPermission.READ, ToolPermission.DATABASE],
            safety_level=ToolSafetyLevel.SAFE,
        )

    def executor(self) -> ToolExecutorProtocol:
        return self.execute

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        memories = await self._memories.list_memories()
        return {
            "memories": [
                memory.model_dump(mode="json")
                for memory in memories
            ],
        }


class GetMemoryTool:
    def __init__(self, memories: MemoryManageProtocol) -> None:
        self._memories = memories

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="get_memory",
            description="Get a runtime memory item",
            parameters_schema={
                "type": "object",
                "properties": {"memory_id": {"type": "string"}},
                "required": ["memory_id"],
            },
            permissions=[ToolPermission.READ, ToolPermission.DATABASE],
            safety_level=ToolSafetyLevel.SAFE,
        )

    def executor(self) -> ToolExecutorProtocol:
        return self.execute

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        memory_id = _required_string(arguments.get("memory_id"), "memory_id")
        memory = await self._memories.get(memory_id)
        return memory.model_dump(mode="json")


class CreateSessionTool:
    def __init__(self, sessions: SessionManageProtocol) -> None:
        self._sessions = sessions

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="create_session",
            description="Create a runtime session",
            parameters_schema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                    "title": {"type": "string"},
                    "context_id": {"type": "string"},
                    "provider_id": {"type": "string"},
                    "model_id": {"type": "string"},
                    "metadata": {"type": "object"},
                },
                "required": ["context_id"],
            },
            permissions=[ToolPermission.WRITE, ToolPermission.DATABASE],
            safety_level=ToolSafetyLevel.SENSITIVE,
            requires_approval=True,
        )

    def executor(self) -> ToolExecutorProtocol:
        return self.execute

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        session_id = _optional_string(arguments.get("session_id")) or (
            f"session-{uuid4().hex}"
        )
        session = Session(
            session_id=session_id,
            title=_optional_string(arguments.get("title")),
            context_id=_required_string(arguments.get("context_id"), "context_id"),
            provider_id=_optional_string(arguments.get("provider_id")),
            model_id=_optional_string(arguments.get("model_id")),
            metadata=_metadata(arguments.get("metadata")),
        )
        created = await self._sessions.create(session)
        return created.model_dump(mode="json")


class ListSessionsTool:
    def __init__(self, sessions: SessionManageProtocol) -> None:
        self._sessions = sessions

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="list_sessions",
            description="List runtime sessions",
            parameters_schema={"type": "object", "properties": {}},
            permissions=[ToolPermission.READ, ToolPermission.DATABASE],
            safety_level=ToolSafetyLevel.SAFE,
        )

    def executor(self) -> ToolExecutorProtocol:
        return self.execute

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        sessions = await self._sessions.list_sessions()
        return {
            "sessions": [
                session.model_dump(mode="json")
                for session in sessions
            ],
        }


class GetSessionTool:
    def __init__(self, sessions: SessionManageProtocol) -> None:
        self._sessions = sessions

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="get_session",
            description="Get a runtime session",
            parameters_schema={
                "type": "object",
                "properties": {"session_id": {"type": "string"}},
                "required": ["session_id"],
            },
            permissions=[ToolPermission.READ, ToolPermission.DATABASE],
            safety_level=ToolSafetyLevel.SAFE,
        )

    def executor(self) -> ToolExecutorProtocol:
        return self.execute

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        session_id = _required_string(arguments.get("session_id"), "session_id")
        session = await self._sessions.get(session_id)
        return session.model_dump(mode="json")


class ArchiveSessionTool:
    def __init__(self, sessions: SessionManageProtocol) -> None:
        self._sessions = sessions

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="archive_session",
            description="Archive a runtime session",
            parameters_schema={
                "type": "object",
                "properties": {"session_id": {"type": "string"}},
                "required": ["session_id"],
            },
            permissions=[ToolPermission.WRITE, ToolPermission.DATABASE],
            safety_level=ToolSafetyLevel.SENSITIVE,
            requires_approval=True,
        )

    def executor(self) -> ToolExecutorProtocol:
        return self.execute

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        session_id = _required_string(arguments.get("session_id"), "session_id")
        session = await self._sessions.archive(session_id)
        return session.model_dump(mode="json")


def _required_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ToolInputError(f"The {name} value must be a non-empty string")
    return value


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ToolInputError("Optional string values must be non-empty strings")
    return value


def _message_role(value: object) -> MessageRole:
    if not isinstance(value, str):
        raise ToolInputError("The role value must be a string")
    try:
        return MessageRole(value)
    except ValueError as exc:
        raise ToolInputError(f"The role {value} is not supported") from exc


def _memory_kind(value: object) -> MemoryKind:
    if value is None:
        return MemoryKind.FACT
    if not isinstance(value, str):
        raise ToolInputError("The memory kind must be a string")
    try:
        return MemoryKind(value)
    except ValueError as exc:
        raise ToolInputError(f"The memory kind {value} is not supported") from exc


def _memory_scope(value: object) -> MemoryScope:
    if value is None:
        return MemoryScope.GLOBAL
    if not isinstance(value, str):
        raise ToolInputError("The memory scope must be a string")
    try:
        return MemoryScope(value)
    except ValueError as exc:
        raise ToolInputError(f"The memory scope {value} is not supported") from exc


def _string_list(value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ToolInputError("The tags value must be a list of strings")
    return value


def _metadata(value: object) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ToolInputError("The metadata value must be a dictionary")
    return dict(value)


def _int(value: object, default: int) -> int:
    if value is None:
        return default
    if not isinstance(value, int):
        raise ToolInputError("The priority value must be an integer")
    return value
