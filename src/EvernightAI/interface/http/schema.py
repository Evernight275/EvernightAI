from pydantic import Field

from EvernightAI.core.schema.base import EvernightAISchema
from EvernightAI.core.schema.content import ChatRequest, ChatSkill, Content
from EvernightAI.core.schema.memory import MemoryQuery
from EvernightAI.core.schema.tool import ToolApprovalDecision, ToolDefinition


class ChatWithContextRequest(EvernightAISchema):
    provider_id: str
    context_id: str
    model_id: str
    messages: list[Content]
    memory_query: MemoryQuery | None = None
    skills: list[ChatSkill] | None = None
    tools: list[ToolDefinition] | None = None
    metadata: dict[str, object] | None = None


class DirectChatRequest(EvernightAISchema):
    provider_id: str
    request: ChatRequest


class ResumeAgentRunRequest(EvernightAISchema):
    approvals: list[ToolApprovalDecision]


class RenderSkillRequest(EvernightAISchema):
    render_id: str | None = None
    variables: dict[str, object] = Field(default_factory=dict)
    metadata: dict[str, object] = Field(default_factory=dict)
