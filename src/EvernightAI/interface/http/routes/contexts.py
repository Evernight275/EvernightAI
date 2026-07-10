from typing import Annotated

from fastapi import APIRouter, Body, Query, Response, status

from EvernightAI.core.schema.content import Content
from EvernightAI.core.schema.context import Context
from EvernightAI.interface.http.dependencies import InterfaceDependency
from EvernightAI.interface.http.template import (
    CONTENT_MESSAGE_EXAMPLES,
    CONTEXT_EXAMPLES,
)


router = APIRouter(prefix="/contexts", tags=["contexts"])


@router.post(
    "",
    response_model=Context,
    response_model_exclude_none=True,
    status_code=status.HTTP_201_CREATED,
    summary="Create a context",
    description=(
        "Create stored conversation history. For a new conversation, an empty "
        "`messages` list is enough."
    ),
    operation_id="create_context",
)
async def create_context(
    context: Annotated[
        Context,
        Body(openapi_examples=CONTEXT_EXAMPLES),
    ],
    interface: InterfaceDependency,
) -> Context:
    return await interface.chat.create_context(context)


@router.get(
    "",
    response_model=list[Context],
    response_model_exclude_none=True,
    summary="List contexts",
    operation_id="list_contexts",
)
async def list_contexts(
    interface: InterfaceDependency,
    cursor: str | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=1000),
    owner_id: str | None = Query(default=None),
) -> list[Context]:
    return await interface.chat.list_contexts(
        cursor=cursor,
        limit=limit,
        owner_id=owner_id,
    )


@router.get(
    "/{context_id}",
    response_model=Context,
    response_model_exclude_none=True,
    summary="Get a context",
    operation_id="get_context",
)
async def get_context(
    context_id: str,
    interface: InterfaceDependency,
) -> Context:
    return await interface.chat.get_context(context_id)


@router.post(
    "/{context_id}/messages",
    response_model=Context,
    response_model_exclude_none=True,
    summary="Append one context message",
    description="Append a single user, assistant, system, or tool message.",
    operation_id="append_context",
)
async def append_context(
    context_id: str,
    message: Annotated[
        Content,
        Body(openapi_examples=CONTENT_MESSAGE_EXAMPLES),
    ],
    interface: InterfaceDependency,
    expected_revision: int | None = Query(default=None, ge=0),
) -> Context:
    return await interface.chat.append_context(
        context_id,
        message,
        expected_revision=expected_revision,
    )


@router.put(
    "/{context_id}",
    response_model=Context,
    response_model_exclude_none=True,
    summary="Replace a context",
    description="Replace all stored messages and metadata for this context id.",
    operation_id="replace_context",
)
async def replace_context(
    context_id: str,
    context: Annotated[
        Context,
        Body(openapi_examples=CONTEXT_EXAMPLES),
    ],
    interface: InterfaceDependency,
) -> Context:
    updated = context if context.context_id == context_id else context.model_copy(
        update={"context_id": context_id}
    )
    return await interface.chat.replace_context(updated)


@router.post(
    "/{context_id}/delete",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete a context",
    operation_id="delete_context",
)
async def delete_context(
    context_id: str,
    interface: InterfaceDependency,
) -> None:
    await interface.chat.delete_context(context_id)
