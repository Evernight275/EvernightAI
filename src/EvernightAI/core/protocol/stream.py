from typing import AsyncIterable, Protocol

from EvernightAI.core.protocol.base import EvernightAIProtocol
from EvernightAI.core.schema.agent import AgentTraceEvent
from EvernightAI.core.schema.stream import ChatStreamEvent, SSEEvent, WebSocketMessage


class SSEProtocol(EvernightAIProtocol, AsyncIterable[SSEEvent], Protocol):
    """SSE协议"""


class ChatStreamProtocol(
    EvernightAIProtocol,
    AsyncIterable[ChatStreamEvent],
    Protocol,
):
    """聊天流式语义协议"""


class AgentTraceStreamProtocol(
    EvernightAIProtocol,
    AsyncIterable[AgentTraceEvent],
    Protocol,
):
    """Agent追踪事件流协议"""


class WebSocketProtocol(EvernightAIProtocol, Protocol):
    """WebSocket双向消息协议"""

    async def receive(self) -> WebSocketMessage:
        """接收一条WebSocket消息"""
        ...

    async def send(self, message: WebSocketMessage) -> None:
        """发送一条WebSocket消息"""
        ...

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        """关闭WebSocket连接"""
        ...
