import re
import hashlib
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
    MemorySort,
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
            memories = select_memories(memories, query).memories
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
        scored: list[tuple[MemoryItem, float, list[str]]] = []
        filtered: list[dict[str, object]] = []
        for memory in memories:
            reasons = self._filter_reasons(memory, query)
            if reasons:
                filtered.append({"memory_id": memory.memory_id, "reasons": reasons})
                continue
            score = _memory_score(memory, query)
            scored.append((memory, score, self._match_reasons(memory, query, score)))

        scored.sort(key=lambda item: _sort_key(item[0], query, item[1]))
        if query.deduplicate:
            deduplicated: list[tuple[MemoryItem, float, list[str]]] = []
            seen: set[tuple[object, ...]] = set()
            for memory, score, reasons in scored:
                key = _deduplication_key(memory, query)
                if key in seen:
                    filtered.append(
                        {
                            "memory_id": memory.memory_id,
                            "reasons": ["duplicate"],
                        }
                    )
                    continue
                seen.add(key)
                deduplicated.append((memory, score, reasons))
            scored = deduplicated

        if query.limit is not None:
            scored = scored[: query.limit]

        selected = [memory for memory, _, _ in scored]
        matches = [
            {
                "memory_id": memory.memory_id,
                "scope": memory.scope.value,
                "scope_id": memory.scope_id,
                "score": score,
                "reasons": reasons,
            }
            for memory, score, reasons in scored
        ]

        return MemorySelection(
            memories=selected,
            metadata={
                "strategy": self.__class__.__name__,
                "total_candidates": len(memories),
                "matched_count": len(scored),
                "selected_count": len(selected),
                "filtered_count": len(filtered),
                "matches": matches,
                "filtered": filtered,
            },
        )

    def _matches(self, memory: MemoryItem, query: MemoryQuery) -> bool:
        return not self._filter_reasons(memory, query)

    def _filter_reasons(self, memory: MemoryItem, query: MemoryQuery) -> list[str]:
        reasons: list[str] = []
        if not query.include_disabled and not memory.is_enabled:
            reasons.append("disabled")
        if not _matches_scope(memory, query):
            reasons.append("scope")
        if query.kinds and memory.kind not in query.kinds:
            reasons.append("kind")
        if query.tags and not set(query.tags).issubset(memory.tags):
            reasons.append("tags")
        if (
            not query.include_expired
            and memory.expires_at is not None
            and memory.expires_at <= datetime.now(timezone.utc)
        ):
            reasons.append("expired")
        if (
            query.minimum_relevance is not None
            and memory.relevance < query.minimum_relevance
        ):
            reasons.append("minimum_relevance")
        if (
            query.minimum_confidence is not None
            and memory.confidence < query.minimum_confidence
        ):
            reasons.append("minimum_confidence")
        if query.text is not None and not _lexical_match(memory, query.text):
            reasons.append("text")
        return reasons

    def _match_reasons(
        self,
        memory: MemoryItem,
        query: MemoryQuery,
        score: float,
    ) -> list[str]:
        reasons = ["enabled" if memory.is_enabled else "disabled_included"]
        if query.text is not None:
            reasons.append("text")
        if query.scopes or query.scope is not None or query.scope_id is not None:
            reasons.append("scope")
        if query.kinds:
            reasons.append("kind")
        if query.tags:
            reasons.append("tags")
        if query.minimum_relevance is not None:
            reasons.append("minimum_relevance")
        if query.minimum_confidence is not None:
            reasons.append("minimum_confidence")
        if score > 0:
            reasons.append("score")
        return reasons


def select_memories(
    memories: list[MemoryItem],
    query: MemoryQuery | None = None,
) -> MemorySelection:
    return BasicMemoryStrategy().select(memories, query)


def _memory_matches(memory: MemoryItem, query: MemoryQuery) -> bool:
    return BasicMemoryStrategy()._matches(memory, query)


def _matches_scope(memory: MemoryItem, query: MemoryQuery) -> bool:
    if query.scopes:
        return any(
            memory.scope is selector.scope and memory.scope_id == selector.scope_id
            for selector in query.scopes
        )
    if query.scope is not None and memory.scope is not query.scope:
        return False
    if query.scope_id is not None and memory.scope_id != query.scope_id:
        return False
    return True


def _scope_rank(memory: MemoryItem, query: MemoryQuery) -> int:
    for index, selector in enumerate(query.scopes):
        if memory.scope is selector.scope and memory.scope_id == selector.scope_id:
            return index
    return len(query.scopes)


def _lexical_tokens(text: str) -> list[str]:
    return re.findall(r"[\w]+", text.casefold())


def _searchable_text(memory: MemoryItem) -> str:
    return " ".join(
        [
            memory.content,
            memory.kind.value,
            memory.scope.value,
            *(memory.tags),
        ]
    ).casefold()


def _lexical_match(memory: MemoryItem, text: str) -> bool:
    tokens = _lexical_tokens(text)
    if not tokens:
        return True
    searchable = _searchable_text(memory)
    return all(token in searchable for token in tokens)


def _lexical_score(memory: MemoryItem, query: MemoryQuery) -> float:
    if query.text is None:
        return 0.0
    tokens = _lexical_tokens(query.text)
    if not tokens:
        return 0.0
    searchable = _searchable_text(memory)
    matches = sum(1 for token in tokens if token in searchable)
    return matches / len(tokens)


def _memory_score(memory: MemoryItem, query: MemoryQuery) -> float:
    return round(
        (memory.priority * 10.0)
        + memory.relevance
        + memory.confidence
        + _lexical_score(memory, query),
        6,
    )


def _sort_key(memory: MemoryItem, query: MemoryQuery, score: float) -> tuple[object, ...]:
    scope_rank = _scope_rank(memory, query)
    if query.sort in {MemorySort.DEFAULT, MemorySort.PRIORITY}:
        return (
            scope_rank,
            -memory.priority,
            -memory.relevance,
            -memory.confidence,
            memory.memory_id,
        )
    if query.sort is MemorySort.RELEVANCE:
        return (
            scope_rank,
            -memory.relevance,
            -memory.priority,
            -memory.confidence,
            memory.memory_id,
        )
    if query.sort is MemorySort.CONFIDENCE:
        return (
            scope_rank,
            -memory.confidence,
            -memory.priority,
            -memory.relevance,
            memory.memory_id,
        )
    if query.sort is MemorySort.UPDATED_AT:
        return (scope_rank, -memory.updated_at.timestamp(), memory.memory_id)
    if query.sort is MemorySort.CREATED_AT:
        return (scope_rank, -memory.created_at.timestamp(), memory.memory_id)
    if query.sort is MemorySort.MEMORY_ID:
        return (scope_rank, memory.memory_id)
    return (scope_rank, -score, memory.memory_id)


def _deduplication_key(memory: MemoryItem, query: MemoryQuery) -> tuple[object, ...]:
    if query.scopes:
        return (
            memory.content.strip().casefold(),
            memory.kind,
            memory.owner_id,
        )
    return (
        memory.content.strip().casefold(),
        memory.kind,
        memory.scope,
        memory.scope_id,
        memory.owner_id,
    )


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
        memory_key = f"agent-summary:{scope.value}:{scope_id}"
        content_fingerprint = _content_fingerprint(content)
        metadata = {
            "source": "agent_run",
            "memory_key": memory_key,
            "content_fingerprint": content_fingerprint,
            "provider_id": request.provider_id,
            "model_id": request.model_id,
            "stop_reason": result.stop_reason.value,
            "step_count": len(result.steps),
            "provenance": {
                "source": "agent_run",
                "provider_id": request.provider_id,
                "model_id": request.model_id,
                "context_id": request.context_id,
                "session_id": session_id,
            },
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


def _content_fingerprint(content: str) -> str:
    normalized = " ".join(content.split()).casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
