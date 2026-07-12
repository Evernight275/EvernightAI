from pydantic import Field

from EvernightAI.core.schema.auth import Principal, PrincipalType
from EvernightAI.core.schema.base import EvernightAISchema
from EvernightAI.core.schema.content import ChatRequest, ChatSkill, Content
from EvernightAI.core.schema.memory import MemoryQuery
from EvernightAI.core.schema.tool import ToolApprovalDecision, ToolDefinition


class HttpApiKeyCredential(EvernightAISchema):
    api_key: str
    principal: Principal


class HttpOAuthBearerCredential(EvernightAISchema):
    access_token: str
    principal: Principal


class HttpOAuthJwtConfig(EvernightAISchema):
    issuer: str
    audience: list[str]
    jwks_url: str
    algorithms: list[str]
    leeway_seconds: int = 60
    principal_id_claim: str = "sub"
    principal_type: PrincipalType = PrincipalType.USER
    roles_claim: str = "roles"
    scope_claim: str = "scope"
    permissions_claim: str = "permissions"
    default_permissions: list[str] = []
    role_permission_map: dict[str, list[str]] = {}
    scope_permission_map: dict[str, list[str]] = {}


class ChatWithContextRequest(EvernightAISchema):
    provider_id: str
    context_id: str
    model_id: str
    messages: list[Content]
    retry_from_message_index: int | None = Field(default=None, ge=0)
    memory_query: MemoryQuery | None = None
    skills: list[ChatSkill] | None = None
    tools: list[ToolDefinition] | None = None
    metadata: dict[str, object] | None = None


class ContextComposePreviewRequest(EvernightAISchema):
    model_id: str
    messages: list[Content] = Field(default_factory=list)
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
