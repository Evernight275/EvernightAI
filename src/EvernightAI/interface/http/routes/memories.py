from typing import Annotated

from fastapi import APIRouter, Body, Query, Response, status

from EvernightAI.core.schema.memory import (
    MemoryItem,
    MemoryKind,
    MemoryQuery,
    MemoryScope,
    MemorySelection,
)
from EvernightAI.interface.http.dependencies import InterfaceDependency
from EvernightAI.interface.http.template import (
    MEMORY_ITEM_EXAMPLES,
    MEMORY_QUERY_EXAMPLES,
)


router = APIRouter(prefix="/memories", tags=["memories"])


@router.post(
    "",
    response_model=MemoryItem,
    response_model_exclude_none=True,
    status_code=status.HTTP_201_CREATED,
    summary="Create a memory",
    description=(
        "Store a durable fact, preference, summary, definition, instruction, "
        "or episodic note. Memory is selected into chat explicitly by query."
    ),
    operation_id="create_memory",
)
async def create_memory(
    memory: Annotated[
        MemoryItem,
        Body(openapi_examples=MEMORY_ITEM_EXAMPLES),
    ],
    interface: InterfaceDependency,
) -> MemoryItem:
    return await interface.chat.create_memory(memory)


@router.get(
    "",
    response_model=list[MemoryItem],
    response_model_exclude_none=True,
    summary="List memories",
    operation_id="list_memories",
)
async def list_memories(
    interface: InterfaceDependency,
    cursor: str | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=1000),
    owner_id: str | None = Query(default=None),
    scope: MemoryScope | None = Query(default=None),
    scope_id: str | None = Query(default=None),
    kind: list[MemoryKind] | None = Query(default=None),
    minimum_relevance: float | None = Query(default=None, ge=0.0, le=1.0),
    minimum_confidence: float | None = Query(default=None, ge=0.0, le=1.0),
    deduplicate: bool | None = Query(default=None),
) -> list[MemoryItem]:
    query = None
    if any(
        value is not None
        for value in (
            scope,
            scope_id,
            kind,
            minimum_relevance,
            minimum_confidence,
            deduplicate,
        )
    ):
        query = MemoryQuery(
            scope=scope,
            scope_id=scope_id,
            kinds=kind or [],
            minimum_relevance=minimum_relevance,
            minimum_confidence=minimum_confidence,
            deduplicate=bool(deduplicate),
        )
    return await interface.chat.list_memories(
        cursor=cursor,
        limit=limit,
        owner_id=owner_id,
        query=query,
    )


@router.get(
    "/{memory_id}",
    response_model=MemoryItem,
    response_model_exclude_none=True,
    summary="Get a memory",
    operation_id="get_memory",
)
async def get_memory(
    memory_id: str,
    interface: InterfaceDependency,
) -> MemoryItem:
    return await interface.chat.get_memory(memory_id)


@router.put(
    "/{memory_id}",
    response_model=MemoryItem,
    response_model_exclude_none=True,
    summary="Replace a memory",
    operation_id="replace_memory",
)
async def replace_memory(
    memory_id: str,
    memory: Annotated[
        MemoryItem,
        Body(openapi_examples=MEMORY_ITEM_EXAMPLES),
    ],
    interface: InterfaceDependency,
) -> MemoryItem:
    updated = memory if memory.memory_id == memory_id else memory.model_copy(
        update={"memory_id": memory_id}
    )
    return await interface.chat.replace_memory(updated)


@router.post(
    "/select",
    response_model=MemorySelection,
    response_model_exclude_none=True,
    summary="Select memories",
    description="Preview which memories match a query before using it in chat.",
    operation_id="select_memories",
)
async def select_memories(
    interface: InterfaceDependency,
    query: Annotated[
        MemoryQuery | None,
        Body(openapi_examples=MEMORY_QUERY_EXAMPLES),
    ] = None,
) -> MemorySelection:
    return await interface.chat.select_memories(query)


@router.post(
    "/{memory_id}/delete",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete a memory",
    operation_id="delete_memory",
)
async def delete_memory(
    memory_id: str,
    interface: InterfaceDependency,
) -> None:
    await interface.chat.delete_memory(memory_id)
