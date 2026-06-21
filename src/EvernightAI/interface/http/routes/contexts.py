from fastapi import APIRouter, Response, status

from EvernightAI.core.schema.content import Content
from EvernightAI.core.schema.context import Context
from EvernightAI.interface.http.dependencies import InterfaceDependency


router = APIRouter(prefix="/contexts", tags=["contexts"])


@router.post(
    "",
    response_model=Context,
    status_code=status.HTTP_201_CREATED,
)
async def create_context(
    context: Context,
    interface: InterfaceDependency,
) -> Context:
    return await interface.chat.create_context(context)


@router.get("", response_model=list[Context])
async def list_contexts(interface: InterfaceDependency) -> list[Context]:
    return await interface.chat.list_contexts()


@router.get("/{context_id}", response_model=Context)
async def get_context(
    context_id: str,
    interface: InterfaceDependency,
) -> Context:
    return await interface.chat.get_context(context_id)


@router.post("/{context_id}/messages", response_model=Context)
async def append_context(
    context_id: str,
    message: Content,
    interface: InterfaceDependency,
) -> Context:
    return await interface.chat.append_context(context_id, message)


@router.put("/{context_id}", response_model=Context)
async def replace_context(
    context_id: str,
    context: Context,
    interface: InterfaceDependency,
) -> Context:
    updated = context if context.context_id == context_id else context.model_copy(
        update={"context_id": context_id}
    )
    return await interface.chat.replace_context(updated)


@router.delete(
    "/{context_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_context(
    context_id: str,
    interface: InterfaceDependency,
) -> None:
    await interface.chat.delete_context(context_id)
