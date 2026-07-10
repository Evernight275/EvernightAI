from uuid import uuid4
from datetime import datetime, timezone

from EvernightAI.core.error.memory import MemoryNotFoundError
from EvernightAI.core.protocol.memory import (
    MemoryManageProtocol,
    MemoryRegisterProtocol,
    MemoryStrategyProtocol,
    MemoryWriteStrategyProtocol,
)
from EvernightAI.core.schema.agent import AgentRunRequest, AgentRunResult
from EvernightAI.core.schema.auth import PrincipalScope
from EvernightAI.core.schema.content import Content, ContentPartType, MessageRole
from EvernightAI.core.schema.memory import (
    MemoryItem,
    MemoryKind,
    MemoryQuery,
    MemoryScope,
    MemorySelection,
)


def _scope_permits(
    principal_scope: PrincipalScope | None,
    owner_id: str | None,
) -> bool:
    return principal_scope is None or principal_scope.permits(owner_id)


def _require_memory_scope(
    memory: MemoryItem,
    principal_scope: PrincipalScope | None,
) -> None:
    if not _scope_permits(principal_scope, memory.owner_id):
        raise MemoryNotFoundError(
            f"The memory {memory.memory_id} is not available in this scope"
        )


class MemoryRegister(MemoryRegisterProtocol):
    def __init__(self) -> None:
        self._memories: dict[str, MemoryItem] = {}

    def register(
        self,
        memory: MemoryItem,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None:
        """注册记忆"""
        _require_memory_scope(memory, principal_scope)
        self._memories[memory.memory_id] = memory

    def unregister(
        self,
        memory_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None:
        """注销记忆"""
        if not self.has(memory_id, principal_scope=principal_scope):
            raise MemoryNotFoundError(f"The memory {memory_id} is not registered")

        self._memories.pop(memory_id, None)

    def get(
        self,
        memory_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> MemoryItem:
        """获取记忆"""
        if self.has(memory_id, principal_scope=principal_scope):
            return self._memories[memory_id]

        raise MemoryNotFoundError(f"The memory {memory_id} is not found")

    def has(
        self,
        memory_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> bool:
        """检查记忆是否存在"""
        memory = self._memories.get(memory_id)
        return memory is not None and _scope_permits(principal_scope, memory.owner_id)

    def list_memories(
        self,
        *,
        cursor: str | None = None,
        limit: int | None = None,
        owner_id: str | None = None,
        query: MemoryQuery | None = None,
        principal_scope: PrincipalScope | None = None,
    ) -> list[MemoryItem]:
        """列出所有记忆"""
        memories = sorted(self._memories.values(), key=lambda item: item.memory_id)
        if cursor is not None:
            memories = [item for item in memories if item.memory_id > cursor]
        if principal_scope is not None and principal_scope.owner_id is not None:
            if owner_id is not None and owner_id != principal_scope.owner_id:
                return []
            owner_id = principal_scope.owner_id
        if owner_id is not None:
            memories = [item for item in memories if item.owner_id == owner_id]
        if query is not None:
            memories = [item for item in memories if _memory_matches(item, query)]
        return memories if limit is None else memories[:limit]


class MemoryManager(MemoryManageProtocol):
    def __init__(self, register: MemoryRegisterProtocol) -> None:
        self._register = register

    async def create(
        self,
        memory: MemoryItem,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> MemoryItem:
        """创建记忆"""
        self._register.register(memory, principal_scope=principal_scope)
        return self._register.get(
            memory.memory_id,
            principal_scope=principal_scope,
        )

    async def get(
        self,
        memory_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> MemoryItem:
        """获取记忆"""
        return self._register.get(memory_id, principal_scope=principal_scope)

    async def replace(
        self,
        memory: MemoryItem,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> MemoryItem:
        """更新记忆"""
        if not self._register.has(
            memory.memory_id,
            principal_scope=principal_scope,
        ):
            raise MemoryNotFoundError(f"The memory {memory.memory_id} is not found")
        updated = memory.model_copy(update={"updated_at": datetime.now(timezone.utc)})
        self._register.register(updated, principal_scope=principal_scope)
        return self._register.get(
            memory.memory_id,
            principal_scope=principal_scope,
        )

    async def list_memories(
        self,
        *,
        cursor: str | None = None,
        limit: int | None = None,
        owner_id: str | None = None,
        query: MemoryQuery | None = None,
        principal_scope: PrincipalScope | None = None,
    ) -> list[MemoryItem]:
        """列出所有记忆"""
        return self._register.list_memories(
            cursor=cursor,
            limit=limit,
            owner_id=owner_id,
            query=query,
            principal_scope=principal_scope,
        )

    async def delete(
        self,
        memory_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None:
        """删除记忆"""
        self._register.unregister(memory_id, principal_scope=principal_scope)

    async def clear(
        self,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None:
        """清空记忆"""
        for memory in list(
            self._register.list_memories(principal_scope=principal_scope)
        ):
            self._register.unregister(
                memory.memory_id,
                principal_scope=principal_scope,
            )


class BasicMemoryStrategy(MemoryStrategyProtocol):
    def select(
        self,
        memories: list[MemoryItem],
        query: MemoryQuery | None = None,
    ) -> MemorySelection:
        """按基础条件选择记忆"""
        query = query or MemoryQuery()
        selected = [memory for memory in memories if self._matches(memory, query)]
        selected.sort(
            key=lambda memory: (
                -memory.priority,
                -memory.relevance,
                -memory.confidence,
                memory.memory_id,
            )
        )
        if query.deduplicate:
            deduplicated: list[MemoryItem] = []
            seen: set[tuple[object, ...]] = set()
            for memory in selected:
                key = (
                    memory.content.strip().casefold(),
                    memory.kind,
                    memory.scope,
                    memory.scope_id,
                    memory.owner_id,
                )
                if key in seen:
                    continue
                seen.add(key)
                deduplicated.append(memory)
            selected = deduplicated

        if query.limit is not None:
            selected = selected[: query.limit]

        return MemorySelection(
            memories=selected,
            metadata={
                "strategy": self.__class__.__name__,
                "total_candidates": len(memories),
                "selected_count": len(selected),
            },
        )

    def _matches(self, memory: MemoryItem, query: MemoryQuery) -> bool:
        if not memory.is_enabled:
            return False
        if query.scope is not None and memory.scope is not query.scope:
            return False
        if query.scope_id is not None and memory.scope_id != query.scope_id:
            return False
        if query.kinds and memory.kind not in query.kinds:
            return False
        if query.tags and not set(query.tags).issubset(memory.tags):
            return False
        if memory.expires_at is not None and memory.expires_at <= datetime.now(timezone.utc):
            return False
        if (
            query.minimum_relevance is not None
            and memory.relevance < query.minimum_relevance
        ):
            return False
        if (
            query.minimum_confidence is not None
            and memory.confidence < query.minimum_confidence
        ):
            return False

        return True


def _memory_matches(memory: MemoryItem, query: MemoryQuery) -> bool:
    return BasicMemoryStrategy()._matches(memory, query)


class BasicMemoryWriteStrategy(MemoryWriteStrategyProtocol):
    SESSION_ID_METADATA_KEY = "session_id"

    def create_memories(
        self,
        request: AgentRunRequest,
        result: AgentRunResult,
    ) -> list[MemoryItem]:
        """按基础规则创建记忆"""
        if not request.write_memory:
            return []

        user_text = self._join_messages(request.messages, MessageRole.USER)
        assistant_text = self._join_messages([result.response.message], MessageRole.ASSISTANT)
        if not user_text and not assistant_text:
            return []

        content = "\n".join(
            part
            for part in [
                f"User: {user_text}" if user_text else "",
                f"Assistant: {assistant_text}" if assistant_text else "",
            ]
            if part
        )
        session_id = self._session_id(request.metadata)
        scope = MemoryScope.SESSION if session_id is not None else MemoryScope.CONTEXT
        scope_id = session_id or request.context_id
        tags = ["agent", "summary", "session"] if session_id else ["agent", "summary"]
        metadata = {
            "provider_id": request.provider_id,
            "model_id": request.model_id,
            "stop_reason": result.stop_reason.value,
            "step_count": len(result.steps),
        }
        if session_id is not None:
            metadata["context_id"] = request.context_id

        return [
            MemoryItem(
                memory_id=f"agent-summary-{uuid4().hex}",
                owner_id=request.owner_id,
                content=content,
                kind=MemoryKind.SUMMARY,
                scope=scope,
                scope_id=scope_id,
                tags=tags,
                metadata=metadata,
            )
        ]

    def _join_messages(self, messages: list[Content], role: MessageRole) -> str:
        texts: list[str] = []
        for message in messages:
            if message.role is not role:
                continue
            for part in message.content or []:
                if part.type is ContentPartType.TEXT and part.text:
                    texts.append(part.text)

        return "\n".join(texts)

    def _session_id(self, metadata: dict[str, object]) -> str | None:
        session_id = metadata.get(self.SESSION_ID_METADATA_KEY)
        if isinstance(session_id, str) and session_id:
            return session_id

        return None
