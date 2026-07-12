from EvernightAI.core.protocol.runtime import RuntimeProtocol
from EvernightAI.core.schema.auth import PrincipalScope
from EvernightAI.core.schema.memory import (
    MemoryItem,
    MemoryQuery,
    MemoryScope,
    MemoryScopeSelector,
    MemorySelection,
    MemoryWriteOperation,
)


def compose_scoped_memory_query(
    *,
    context_id: str | None = None,
    session_id: str | None = None,
    user_id: str | None = None,
) -> MemoryQuery:
    scopes: list[MemoryScopeSelector] = []
    if context_id:
        scopes.append(MemoryScopeSelector(scope=MemoryScope.CONTEXT, scope_id=context_id))
    if session_id:
        scopes.append(MemoryScopeSelector(scope=MemoryScope.SESSION, scope_id=session_id))
    if user_id:
        scopes.append(MemoryScopeSelector(scope=MemoryScope.USER, scope_id=user_id))
    scopes.append(MemoryScopeSelector(scope=MemoryScope.GLOBAL))
    return MemoryQuery(scopes=scopes, deduplicate=True)


async def select_memories_for_request(
    runtime: RuntimeProtocol,
    *,
    explicit_query: MemoryQuery | None = None,
    context_id: str | None = None,
    metadata: dict[str, object] | None = None,
    owner_id: str | None = None,
    principal_scope: PrincipalScope | None = None,
) -> MemorySelection | None:
    query = explicit_query or compose_scoped_memory_query(
        context_id=context_id,
        session_id=_metadata_text(metadata, "session_id"),
        user_id=owner_id or (principal_scope.owner_id if principal_scope else None),
    )
    memories = await runtime.memories.list_memories(
        principal_scope=principal_scope,
    )
    selection = runtime.memory_strategy.select(memories, query)
    if not selection.memories:
        return None
    return selection


async def write_memory_candidate(
    runtime: RuntimeProtocol,
    memory: MemoryItem,
    *,
    principal_scope: PrincipalScope | None = None,
) -> tuple[MemoryItem, MemoryWriteOperation]:
    existing = await _find_existing_memory(
        runtime,
        memory,
        principal_scope=principal_scope,
    )
    if existing is None:
        created = memory.model_copy(
            update={"metadata": _with_write_operation(memory, MemoryWriteOperation.CREATE)}
        )
        return (
            await runtime.memories.create(
                created,
                principal_scope=principal_scope,
            ),
            MemoryWriteOperation.CREATE,
        )

    operation = (
        MemoryWriteOperation.MERGE
        if existing.metadata.get("content_fingerprint")
        == memory.metadata.get("content_fingerprint")
        else MemoryWriteOperation.REPLACE
    )
    replacement = _merge_memory(existing, memory, operation)
    return (
        await runtime.memories.replace(
            replacement,
            principal_scope=principal_scope,
        ),
        operation,
    )


def _metadata_text(metadata: dict[str, object] | None, key: str) -> str | None:
    value = (metadata or {}).get(key)
    if isinstance(value, str) and value:
        return value
    return None


async def _find_existing_memory(
    runtime: RuntimeProtocol,
    candidate: MemoryItem,
    *,
    principal_scope: PrincipalScope | None,
) -> MemoryItem | None:
    memory_key = candidate.metadata.get("memory_key")
    if not isinstance(memory_key, str) or not memory_key:
        return None

    memories = await runtime.memories.list_memories(
        query=MemoryQuery(
            scope=candidate.scope,
            scope_id=candidate.scope_id,
            kinds=[candidate.kind],
            include_disabled=True,
            include_expired=True,
        ),
        principal_scope=principal_scope,
    )
    for memory in memories:
        if memory.owner_id != candidate.owner_id:
            continue
        if memory.metadata.get("memory_key") == memory_key:
            return memory
    return None


def _merge_memory(
    existing: MemoryItem,
    candidate: MemoryItem,
    operation: MemoryWriteOperation,
) -> MemoryItem:
    metadata = _with_write_operation(candidate, operation)
    metadata["previous_memory_id"] = existing.memory_id
    previous_fingerprint = existing.metadata.get("content_fingerprint")
    if isinstance(previous_fingerprint, str):
        metadata["previous_content_fingerprint"] = previous_fingerprint
    metadata["provenance"] = _merge_provenance(
        existing.metadata.get("provenance"),
        candidate.metadata.get("provenance"),
    )

    if operation is MemoryWriteOperation.MERGE:
        return existing.model_copy(
            update={
                "tags": _merged_tags(existing.tags, candidate.tags),
                "priority": max(existing.priority, candidate.priority),
                "relevance": max(existing.relevance, candidate.relevance),
                "confidence": max(existing.confidence, candidate.confidence),
                "expires_at": candidate.expires_at or existing.expires_at,
                "metadata": {**existing.metadata, **metadata},
            }
        )

    return candidate.model_copy(
        update={
            "memory_id": existing.memory_id,
            "metadata": {
                **existing.metadata,
                **metadata,
            },
        }
    )


def _with_write_operation(
    memory: MemoryItem,
    operation: MemoryWriteOperation,
) -> dict[str, object]:
    return {
        **memory.metadata,
        "write_operation": operation.value,
    }


def _merge_provenance(existing: object, candidate: object) -> dict[str, object]:
    events: list[object] = []
    if isinstance(existing, dict):
        existing_events = existing.get("events")
        if isinstance(existing_events, list):
            events.extend(existing_events)
        else:
            events.append(existing)
    if isinstance(candidate, dict):
        candidate_events = candidate.get("events")
        if isinstance(candidate_events, list):
            events.extend(candidate_events)
        else:
            events.append(candidate)
    return {"events": events}


def _merged_tags(left: list[str], right: list[str]) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()
    for tag in [*left, *right]:
        if tag in seen:
            continue
        seen.add(tag)
        tags.append(tag)
    return tags
