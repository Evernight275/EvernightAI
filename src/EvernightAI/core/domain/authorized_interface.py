from EvernightAI.core.protocol.auth import AuthorizerProtocol
from EvernightAI.core.protocol.interface import (
    AgentInterfaceProtocol,
    AgentRunInterfaceProtocol,
    ChatInterfaceProtocol,
    EvernightInterfaceProtocol,
    ProviderInterfaceProtocol,
    SessionInterfaceProtocol,
    SkillInterfaceProtocol,
    ToolInterfaceProtocol,
)
from EvernightAI.core.protocol.provider import ProviderInstanceProtocol
from EvernightAI.core.protocol.runtime import RuntimeProtocol
from EvernightAI.core.protocol.stream import AgentTraceStreamProtocol, ChatStreamProtocol
from EvernightAI.core.schema.agent import (
    AgentRunRequest,
    AgentRunResult,
    AgentRunState,
    AgentTraceEvent,
)
from EvernightAI.core.schema.auth import AuthPermission, AuthRequest, Principal
from EvernightAI.core.schema.content import ChatRequest, ChatResponse, ChatSkill, Content
from EvernightAI.core.schema.context import Context
from EvernightAI.core.schema.memory import MemoryItem, MemoryQuery, MemorySelection
from EvernightAI.core.schema.provider import (
    ProviderConfig,
    ProviderInfo,
    ProviderModelCapability,
    ProviderModelConfig,
)
from EvernightAI.core.schema.session import (
    Session,
    SessionAgentRunRequest,
    SessionChatRequest,
    SessionChatResult,
)
from EvernightAI.core.schema.skill import (
    RenderedSkill,
    SkillCapability,
    SkillDefinition,
    SkillRenderRequest,
)
from EvernightAI.core.schema.tool import ToolApprovalDecision, ToolDefinition


class AuthorizedEvernightInterface(EvernightInterfaceProtocol):
    def __init__(
        self,
        interface: EvernightInterfaceProtocol,
        authorizer: AuthorizerProtocol,
        principal: Principal,
    ) -> None:
        self._interface = interface
        self._authorizer = authorizer
        self._principal = principal
        self._chat = AuthorizedChatInterface(
            interface.chat,
            authorizer,
            principal,
        )
        self._providers = AuthorizedProviderInterface(
            interface.providers,
            authorizer,
            principal,
        )
        self._tools = AuthorizedToolInterface(
            interface.tools,
            authorizer,
            principal,
        )
        self._agent = AuthorizedAgentInterface(
            interface.agent,
            authorizer,
            principal,
        )
        self._agent_runs = AuthorizedAgentRunInterface(
            interface.agent_runs,
            authorizer,
            principal,
        )
        self._skills = AuthorizedSkillInterface(
            interface.skills,
            authorizer,
            principal,
        )
        self._sessions = AuthorizedSessionInterface(
            interface.sessions,
            authorizer,
            principal,
        )

    @property
    def runtime(self) -> RuntimeProtocol:
        return self._interface.runtime

    @property
    def chat(self) -> ChatInterfaceProtocol:
        return self._chat

    @property
    def agent(self) -> AgentInterfaceProtocol:
        return self._agent

    @property
    def agent_runs(self) -> AgentRunInterfaceProtocol:
        return self._agent_runs

    @property
    def providers(self) -> ProviderInterfaceProtocol:
        return self._providers

    @property
    def tools(self) -> ToolInterfaceProtocol:
        return self._tools

    @property
    def skills(self) -> SkillInterfaceProtocol:
        return self._skills

    @property
    def sessions(self) -> SessionInterfaceProtocol:
        return self._sessions

    async def close(self) -> None:
        await self._interface.close()


class AuthorizedChatInterface(ChatInterfaceProtocol):
    def __init__(
        self,
        inner: ChatInterfaceProtocol,
        authorizer: AuthorizerProtocol,
        principal: Principal,
    ) -> None:
        self._inner = inner
        self._authorizer = authorizer
        self._principal = principal

    async def create_provider(
        self,
        config: ProviderConfig,
    ) -> ProviderInstanceProtocol:
        self._require("providers", "create", config.provider_id)
        return await self._inner.create_provider(config)

    async def create_context(self, context: Context) -> Context:
        self._require("contexts", "create", context.context_id)
        return await self._inner.create_context(context)

    async def get_context(self, context_id: str) -> Context:
        self._require("contexts", "get", context_id)
        return await self._inner.get_context(context_id)

    async def append_context(self, context_id: str, message: Content) -> Context:
        self._require("contexts", "append", context_id)
        return await self._inner.append_context(context_id, message)

    async def replace_context(self, context: Context) -> Context:
        self._require("contexts", "replace", context.context_id)
        return await self._inner.replace_context(context)

    async def list_contexts(self) -> list[Context]:
        self._require("contexts", "list")
        return await self._inner.list_contexts()

    async def delete_context(self, context_id: str) -> None:
        self._require("contexts", "delete", context_id)
        await self._inner.delete_context(context_id)

    async def create_memory(self, memory: MemoryItem) -> MemoryItem:
        self._require("memories", "create", memory.memory_id)
        return await self._inner.create_memory(memory)

    async def get_memory(self, memory_id: str) -> MemoryItem:
        self._require("memories", "get", memory_id)
        return await self._inner.get_memory(memory_id)

    async def list_memories(self) -> list[MemoryItem]:
        self._require("memories", "list")
        return await self._inner.list_memories()

    async def delete_memory(self, memory_id: str) -> None:
        self._require("memories", "delete", memory_id)
        await self._inner.delete_memory(memory_id)

    async def select_memories(
        self,
        query: MemoryQuery | None = None,
    ) -> MemorySelection:
        self._require("memories", "select")
        return await self._inner.select_memories(query)

    async def chat(self, provider_id: str, request: ChatRequest) -> ChatResponse:
        self._require("chat", "create", provider_id)
        return await self._inner.chat(provider_id, request)

    async def chat_with_context(
        self,
        provider_id: str,
        context_id: str,
        *,
        model_id: str,
        messages: list[Content],
        memory_query: MemoryQuery | None = None,
        skills: list[ChatSkill] | None = None,
        tools: list[ToolDefinition] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> ChatResponse:
        self._require("chat", "create", context_id)
        return await self._inner.chat_with_context(
            provider_id,
            context_id,
            model_id=model_id,
            messages=messages,
            memory_query=memory_query,
            skills=skills,
            tools=tools,
            metadata=metadata,
        )

    async def chat_stream(
        self,
        provider_id: str,
        request: ChatRequest,
    ) -> ChatStreamProtocol:
        self._require("chat", "stream", provider_id)
        return await self._inner.chat_stream(provider_id, request)

    async def chat_stream_with_context(
        self,
        provider_id: str,
        context_id: str,
        *,
        model_id: str,
        messages: list[Content],
        memory_query: MemoryQuery | None = None,
        skills: list[ChatSkill] | None = None,
        tools: list[ToolDefinition] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> ChatStreamProtocol:
        self._require("chat", "stream", context_id)
        return await self._inner.chat_stream_with_context(
            provider_id,
            context_id,
            model_id=model_id,
            messages=messages,
            memory_query=memory_query,
            skills=skills,
            tools=tools,
            metadata=metadata,
        )

    async def close(self) -> None:
        await self._inner.close()

    def _require(
        self,
        resource: str,
        action: str,
        resource_id: str | None = None,
    ) -> None:
        require_permission(
            self._authorizer,
            self._principal,
            resource,
            action,
            resource_id,
        )


class AuthorizedProviderInterface(ProviderInterfaceProtocol):
    def __init__(
        self,
        inner: ProviderInterfaceProtocol,
        authorizer: AuthorizerProtocol,
        principal: Principal,
    ) -> None:
        self._inner = inner
        self._authorizer = authorizer
        self._principal = principal

    async def create_provider(self, config: ProviderConfig) -> ProviderInfo:
        self._require("providers", "create", config.provider_id)
        return await self._inner.create_provider(config)

    async def list_provider_models(
        self,
        provider_id: str,
    ) -> list[ProviderModelConfig]:
        self._require("providers", "list_models", provider_id)
        return await self._inner.list_provider_models(provider_id)

    async def get_provider_model(
        self,
        provider_id: str,
        model_id: str,
    ) -> ProviderModelConfig:
        self._require("providers", "get_model", provider_id)
        return await self._inner.get_provider_model(provider_id, model_id)

    async def provider_supports(
        self,
        provider_id: str,
        capability: ProviderModelCapability,
    ) -> bool:
        self._require("providers", "supports", provider_id)
        return await self._inner.provider_supports(provider_id, capability)

    async def delete_provider(self, provider_id: str) -> None:
        self._require("providers", "delete", provider_id)
        await self._inner.delete_provider(provider_id)

    def _require(
        self,
        resource: str,
        action: str,
        resource_id: str | None = None,
    ) -> None:
        require_permission(
            self._authorizer,
            self._principal,
            resource,
            action,
            resource_id,
        )


class AuthorizedToolInterface(ToolInterfaceProtocol):
    def __init__(
        self,
        inner: ToolInterfaceProtocol,
        authorizer: AuthorizerProtocol,
        principal: Principal,
    ) -> None:
        self._inner = inner
        self._authorizer = authorizer
        self._principal = principal

    def list_tools(self) -> list[ToolDefinition]:
        require_permission(self._authorizer, self._principal, "tools", "list")
        return self._inner.list_tools()


class AuthorizedAgentInterface(AgentInterfaceProtocol):
    def __init__(
        self,
        inner: AgentInterfaceProtocol,
        authorizer: AuthorizerProtocol,
        principal: Principal,
    ) -> None:
        self._inner = inner
        self._authorizer = authorizer
        self._principal = principal

    async def run_agent(self, request: AgentRunRequest) -> AgentRunResult:
        self._require("agent", "run", request.context_id)
        return await self._inner.run_agent(request)

    async def run_agent_until_pause(
        self,
        request: AgentRunRequest,
    ) -> AgentRunState:
        self._require("agent", "run", request.context_id)
        return await self._inner.run_agent_until_pause(request)

    async def resume_agent(
        self,
        state: AgentRunState,
        approvals: list[ToolApprovalDecision],
    ) -> AgentRunResult:
        self._require("agent", "resume", state.run_id)
        return await self._inner.resume_agent(state, approvals)

    async def resume_agent_until_pause(
        self,
        state: AgentRunState,
        approvals: list[ToolApprovalDecision],
    ) -> AgentRunState:
        self._require("agent", "resume", state.run_id)
        return await self._inner.resume_agent_until_pause(state, approvals)

    async def start_agent_run(self, request: AgentRunRequest) -> AgentRunState:
        self._require("agent-runs", "create", request.context_id)
        return await self._inner.start_agent_run(request)

    async def resume_agent_run(
        self,
        run_id: str,
        approvals: list[ToolApprovalDecision],
    ) -> AgentRunState:
        self._require("agent-runs", "resume", run_id)
        return await self._inner.resume_agent_run(run_id, approvals)

    def run_agent_stream(
        self,
        request: AgentRunRequest,
    ) -> AgentTraceStreamProtocol:
        self._require("agent", "stream", request.context_id)
        return self._inner.run_agent_stream(request)

    def resume_agent_stream(
        self,
        state: AgentRunState,
        approvals: list[ToolApprovalDecision],
    ) -> AgentTraceStreamProtocol:
        self._require("agent", "resume_stream", state.run_id)
        return self._inner.resume_agent_stream(state, approvals)

    async def run(
        self,
        provider_id: str,
        context_id: str,
        *,
        model_id: str,
        messages: list[Content],
        memory_query: MemoryQuery | None = None,
        skills: list[ChatSkill] | None = None,
        tools: list[ToolDefinition] | None = None,
        metadata: dict[str, object] | None = None,
        max_tool_rounds: int = 1,
    ) -> ChatResponse:
        self._require("agent", "run", context_id)
        return await self._inner.run(
            provider_id,
            context_id,
            model_id=model_id,
            messages=messages,
            memory_query=memory_query,
            skills=skills,
            tools=tools,
            metadata=metadata,
            max_tool_rounds=max_tool_rounds,
        )

    def _require(
        self,
        resource: str,
        action: str,
        resource_id: str | None = None,
    ) -> None:
        require_permission(
            self._authorizer,
            self._principal,
            resource,
            action,
            resource_id,
        )


class AuthorizedAgentRunInterface(AgentRunInterfaceProtocol):
    def __init__(
        self,
        inner: AgentRunInterfaceProtocol,
        authorizer: AuthorizerProtocol,
        principal: Principal,
    ) -> None:
        self._inner = inner
        self._authorizer = authorizer
        self._principal = principal

    async def start(self, request: AgentRunRequest) -> AgentRunState:
        self._require("agent-runs", "create", request.context_id)
        return await self._inner.start(request)

    async def resume(
        self,
        run_id: str,
        approvals: list[ToolApprovalDecision],
    ) -> AgentRunState:
        self._require("agent-runs", "resume", run_id)
        return await self._inner.resume(run_id, approvals)

    def start_stream(
        self,
        request: AgentRunRequest,
    ) -> AgentTraceStreamProtocol:
        self._require("agent-runs", "stream", request.context_id)
        return self._inner.start_stream(request)

    def resume_stream(
        self,
        run_id: str,
        approvals: list[ToolApprovalDecision],
    ) -> AgentTraceStreamProtocol:
        self._require("agent-runs", "resume_stream", run_id)
        return self._inner.resume_stream(run_id, approvals)

    def get_state(self, run_id: str) -> AgentRunState:
        self._require("agent-runs", "get", run_id)
        return self._inner.get_state(run_id)

    def list_states(self) -> list[AgentRunState]:
        self._require("agent-runs", "list")
        return self._inner.list_states()

    def list_trace(self, run_id: str) -> list[AgentTraceEvent]:
        self._require("agent-runs", "list_trace", run_id)
        return self._inner.list_trace(run_id)

    async def close(self) -> None:
        await self._inner.close()

    def _require(
        self,
        resource: str,
        action: str,
        resource_id: str | None = None,
    ) -> None:
        require_permission(
            self._authorizer,
            self._principal,
            resource,
            action,
            resource_id,
        )


class AuthorizedSkillInterface(SkillInterfaceProtocol):
    def __init__(
        self,
        inner: SkillInterfaceProtocol,
        authorizer: AuthorizerProtocol,
        principal: Principal,
    ) -> None:
        self._inner = inner
        self._authorizer = authorizer
        self._principal = principal

    def list_skills(self) -> list[SkillDefinition]:
        self._require("skills", "list")
        return self._inner.list_skills()

    def get_skill(self, skill_name: str) -> SkillDefinition:
        self._require("skills", "get", skill_name)
        return self._inner.get_skill(skill_name)

    def skill_supports(
        self,
        skill_name: str,
        capability: SkillCapability,
    ) -> bool:
        self._require("skills", "supports", skill_name)
        return self._inner.skill_supports(skill_name, capability)

    async def render_skill(self, request: SkillRenderRequest) -> RenderedSkill:
        self._require("skills", "render", request.skill_name)
        return await self._inner.render_skill(request)

    def _require(
        self,
        resource: str,
        action: str,
        resource_id: str | None = None,
    ) -> None:
        require_permission(
            self._authorizer,
            self._principal,
            resource,
            action,
            resource_id,
        )


class AuthorizedSessionInterface(SessionInterfaceProtocol):
    def __init__(
        self,
        inner: SessionInterfaceProtocol,
        authorizer: AuthorizerProtocol,
        principal: Principal,
    ) -> None:
        self._inner = inner
        self._authorizer = authorizer
        self._principal = principal

    async def create_session(self, session: Session) -> Session:
        self._require("sessions", "create", session.session_id)
        return await self._inner.create_session(session)

    async def get_session(self, session_id: str) -> Session:
        self._require("sessions", "get", session_id)
        return await self._inner.get_session(session_id)

    async def replace_session(self, session: Session) -> Session:
        self._require("sessions", "replace", session.session_id)
        return await self._inner.replace_session(session)

    async def archive_session(self, session_id: str) -> Session:
        self._require("sessions", "archive", session_id)
        return await self._inner.archive_session(session_id)

    async def list_sessions(self) -> list[Session]:
        self._require("sessions", "list")
        return await self._inner.list_sessions()

    async def delete_session(self, session_id: str) -> None:
        self._require("sessions", "delete", session_id)
        await self._inner.delete_session(session_id)

    async def chat_with_session(
        self,
        session_id: str,
        request: SessionChatRequest,
    ) -> SessionChatResult:
        self._require("sessions", "chat", session_id)
        return await self._inner.chat_with_session(session_id, request)

    async def start_agent_run_for_session(
        self,
        session_id: str,
        request: SessionAgentRunRequest,
    ) -> AgentRunState:
        self._require("sessions", "start_agent_run", session_id)
        return await self._inner.start_agent_run_for_session(session_id, request)

    def _require(
        self,
        resource: str,
        action: str,
        resource_id: str | None = None,
    ) -> None:
        require_permission(
            self._authorizer,
            self._principal,
            resource,
            action,
            resource_id,
        )


def require_permission(
    authorizer: AuthorizerProtocol,
    principal: Principal,
    resource: str,
    action: str,
    resource_id: str | None = None,
) -> None:
    authorizer.require(
        AuthRequest(
            principal=principal,
            permission=AuthPermission(resource=resource, action=action),
            resource_id=resource_id,
        )
    )
