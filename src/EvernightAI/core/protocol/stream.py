from typing import AsyncIterable, Protocol

from EvernightAI.core.protocol.base import EvernightAIProtocol
from EvernightAI.core.schema.stream import SSEEvent


class SSEProtocol(EvernightAIProtocol, AsyncIterable[SSEEvent], Protocol):
    """SSE协议"""
