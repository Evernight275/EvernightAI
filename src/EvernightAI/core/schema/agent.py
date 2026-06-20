from enum import StrEnum
from typing import Any

from pydantic import Field

from EvernightAI.core.schema.base import EvernightAISchema
from EvernightAI.core.schema.content import ChatResponse, Content
from EvernightAI.core.schema.memory import MemoryQuery
from EvernightAI.core.schema.tool import ToolCall, ToolCallResult, ToolDefinition


class AgentStepType(StrEnum):
    """Agent步骤类型"""

    START = "start"
    CHAT = "chat"
    TOOL = "tool"
    TOOL_ERROR = "tool_error"
    MEMORY_WRITE = "memory_write"
    STOP = "stop"


class AgentStopReason(StrEnum):
    """Agent停止原因"""

    FINISHED = "finished"
    TOOL_ROUNDS_EXHAUSTED = "tool_rounds_exhausted"
    TOOL_ERROR = "tool_error"


class AgentRunRequest(EvernightAISchema):
    """Agent运行请求"""

    provider_id: str
    context_id: str
    model_id: str
    messages: list[Content] = Field(default_factory=list)
    memory_query: MemoryQuery | None = None
    tools: list[ToolDefinition] | None = None
    max_tool_rounds: int = Field(default=1, ge=0)
    recover_tool_errors: bool = True
    write_memory: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentStep(EvernightAISchema):
    """Agent运行步骤"""

    step_type: AgentStepType
    response: ChatResponse | None = None
    message: Content | None = None
    tool_call: ToolCall | None = None
    tool_result: ToolCallResult | None = None
    error_type: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentRunResult(EvernightAISchema):
    """Agent运行结果"""

    response: ChatResponse
    stop_reason: AgentStopReason = AgentStopReason.FINISHED
    steps: list[AgentStep] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
