from fastapi import APIRouter, Response, status

from EvernightAI.core.schema.memory import MemoryItem, MemoryQuery, MemorySelection
from EvernightAI.interface.http.dependencies import InterfaceDependency


router = APIRouter(prefix="/memories", tags=["memories"])


@router.post(
    "",
    response_model=MemoryItem,
    status_code=status.HTTP_201_CREATED,
)
async def create_memory(
    memory: MemoryItem,
    interface: InterfaceDependency,
) -> MemoryItem:
    return await interface.chat.create_memory(memory)


@router.get("", response_model=list[MemoryItem])
async def list_memories(interface: InterfaceDependency) -> list[MemoryItem]:
    return await interface.chat.list_memories()


@router.get("/{memory_id}", response_model=MemoryItem)
async def get_memory(
    memory_id: str,
    interface: InterfaceDependency,
) -> MemoryItem:
    return await interface.chat.get_memory(memory_id)


@router.post("/select", response_model=MemorySelection)
async def select_memories(
    interface: InterfaceDependency,
    query: MemoryQuery | None = None,
) -> MemorySelection:
    return await interface.chat.select_memories(query)


@router.delete(
    "/{memory_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_memory(
    memory_id: str,
    interface: InterfaceDependency,
) -> None:
    await interface.chat.delete_memory(memory_id)
