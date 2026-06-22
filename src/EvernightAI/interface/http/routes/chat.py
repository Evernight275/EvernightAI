from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from EvernightAI.core.schema.content import ChatResponse
from EvernightAI.interface.http.dependencies import InterfaceDependency
from EvernightAI.interface.http.schema import (
    ChatWithContextRequest,
    DirectChatRequest,
)
from EvernightAI.interface.http.sse import sse_response_body


router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat(
    request: DirectChatRequest,
    interface: InterfaceDependency,
) -> ChatResponse:
    return await interface.chat.chat(request.provider_id, request.request)


@router.post("/stream")
async def chat_stream(
    request: DirectChatRequest,
    interface: InterfaceDependency,
) -> StreamingResponse:
    stream = await interface.chat.chat_stream(request.provider_id, request.request)
    return StreamingResponse(
        sse_response_body(stream),
        media_type="text/event-stream",
    )


@router.post("/context", response_model=ChatResponse)
async def chat_with_context(
    request: ChatWithContextRequest,
    interface: InterfaceDependency,
) -> ChatResponse:
    return await interface.chat.chat_with_context(
        request.provider_id,
        request.context_id,
        model_id=request.model_id,
        messages=request.messages,
        memory_query=request.memory_query,
        tools=request.tools,
        metadata=request.metadata,
    )
