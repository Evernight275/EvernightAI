from typing import Annotated

from fastapi import APIRouter, Body
from fastapi.responses import StreamingResponse

from EvernightAI.core.schema.content import ChatResponse
from EvernightAI.interface.http.dependencies import InterfaceDependency
from EvernightAI.interface.http.schema import (
    ChatWithContextRequest,
    DirectChatRequest,
)
from EvernightAI.interface.http.template import (
    CHAT_WITH_CONTEXT_EXAMPLES,
    CHAT_RESPONSE_EXAMPLE,
    CHAT_STREAM_ERROR_SSE_EXAMPLE,
    DIRECT_CHAT_EXAMPLES,
)
from EvernightAI.interface.http.sse import chat_stream_response_body


router = APIRouter(prefix="/chat", tags=["chat"])


@router.post(
    "",
    response_model=ChatResponse,
    response_model_exclude_none=True,
    summary="Send a one-off chat request",
    description=(
        "Call a registered provider directly. This does not read or write a "
        "stored context."
    ),
    operation_id="chat",
    responses={200: CHAT_RESPONSE_EXAMPLE},
)
async def chat(
    request: Annotated[
        DirectChatRequest,
        Body(openapi_examples=DIRECT_CHAT_EXAMPLES),
    ],
    interface: InterfaceDependency,
) -> ChatResponse:
    return await interface.chat.chat(request.provider_id, request.request)


@router.post(
    "/stream",
    summary="Stream a one-off chat request",
    description="SSE transport for `POST /chat`; events contain normalized chat stream data.",
    operation_id="chat_stream",
    responses={200: CHAT_STREAM_ERROR_SSE_EXAMPLE},
)
async def chat_stream(
    request: Annotated[
        DirectChatRequest,
        Body(openapi_examples=DIRECT_CHAT_EXAMPLES),
    ],
    interface: InterfaceDependency,
) -> StreamingResponse:
    stream = await interface.chat.chat_stream(request.provider_id, request.request)
    return StreamingResponse(
        chat_stream_response_body(stream),
        media_type="text/event-stream",
    )


@router.post(
    "/context",
    response_model=ChatResponse,
    response_model_exclude_none=True,
    summary="Chat with stored context",
    description=(
        "Compose the stored context messages first, append the request messages, "
        "call the provider, then persist the new user and assistant messages."
    ),
    operation_id="chat_with_context",
    responses={200: CHAT_RESPONSE_EXAMPLE},
)
async def chat_with_context(
    request: Annotated[
        ChatWithContextRequest,
        Body(openapi_examples=CHAT_WITH_CONTEXT_EXAMPLES),
    ],
    interface: InterfaceDependency,
) -> ChatResponse:
    return await interface.chat.chat_with_context(
        request.provider_id,
        request.context_id,
        model_id=request.model_id,
        messages=request.messages,
        retry_from_message_index=request.retry_from_message_index,
        memory_query=request.memory_query,
        skills=request.skills,
        tools=request.tools,
        metadata=request.metadata,
    )


@router.post(
    "/context/stream",
    summary="Stream chat with stored context",
    description=(
        "SSE transport for context chat. The completed streamed assistant "
        "message is persisted to the context."
    ),
    operation_id="chat_context_stream",
    responses={200: CHAT_STREAM_ERROR_SSE_EXAMPLE},
)
async def chat_context_stream(
    request: Annotated[
        ChatWithContextRequest,
        Body(openapi_examples=CHAT_WITH_CONTEXT_EXAMPLES),
    ],
    interface: InterfaceDependency,
) -> StreamingResponse:
    stream = await interface.chat.chat_stream_with_context(
        request.provider_id,
        request.context_id,
        model_id=request.model_id,
        messages=request.messages,
        retry_from_message_index=request.retry_from_message_index,
        memory_query=request.memory_query,
        skills=request.skills,
        tools=request.tools,
        metadata=request.metadata,
    )
    return StreamingResponse(
        chat_stream_response_body(stream),
        media_type="text/event-stream",
    )
