from typing import AsyncIterable, Protocol

from EvernightAI.core.protocol.base import EvernightAIProtocol
from EvernightAI.core.schema.agent import AgentTraceEvent
from EvernightAI.core.schema.stream import SSEEvent


class SSEProtocol(EvernightAIProtocol, AsyncIterable[SSEEvent], Protocol):
    """SSE协议"""


class AgentTraceStreamProtocol(
    EvernightAIProtocol,
    AsyncIterable[AgentTraceEvent],
    Protocol,
):
    """Agent追踪事件流协议"""
