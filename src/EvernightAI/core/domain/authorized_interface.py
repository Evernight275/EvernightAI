from collections.abc import Awaitable, Callable
from typing import TypeVar

from EvernightAI.core.protocol.auth import AuthorizerProtocol
from EvernightAI.core.protocol.interface import (
    AgentInterfaceProtocol,
    AgentRunInterfaceProtocol,
    ChatInterfaceProtocol,
    DataAnalysisInterfaceProtocol,
    EvernightInterfaceProtocol,
    ProviderInterfaceProtocol,
    SessionInterfaceProtocol,
    SkillInterfaceProtocol,
    ToolInterfaceProtocol,
)
from EvernightAI.core.protocol.runtime import RuntimeProtocol
from EvernightAI.core.protocol.stream import AgentTraceStreamProtocol, ChatStreamProtocol
from EvernightAI.core.schema.agent import (
    AgentRunRequest,
    AgentRunResult,
    AgentRunState,
    AgentRunStatus,
    AgentTraceEvent,
)
from EvernightAI.core.schema.auth import (
    AuthPermission,
    AuthRequest,
    Principal,
    PrincipalScope,
)
from EvernightAI.core.schema.content import ChatRequest, ChatResponse, ChatSkill, Content
from EvernightAI.core.schema.context import Context
from EvernightAI.core.schema.data_analysis import (
    DataAnalysisRequest,
    DataAnalysisResult,
    DataFieldDefinition,
    DataMetricDefinition,
    DataSourceDefinition,
    DataStatisticsRequest,
    DataStatisticsResult,
)
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
    SessionStatus,
)
from EvernightAI.core.schema.skill import (
    RenderedSkill,
    SkillCapability,
    SkillDefinition,
    SkillRenderRequest,
)
from EvernightAI.core.schema.tool import ToolApprovalDecision, ToolDefinition


ScopedResult = TypeVar("ScopedResult")


async def _call_with_scope(
    operation: Callable[..., Awaitable[ScopedResult]],
    *args: object,
    principal_scope: PrincipalScope,
    **kwargs: object,
) -> ScopedResult:
    try:
        return await operation(
            *args,
            **kwargs,
            principal_scope=principal_scope,
        )
    except TypeError as exc:
        if "principal_scope" not in str(exc):
            raise
        return await operation(*args, **kwargs)


def _call_with_scope_sync(
    operation: Callable[..., ScopedResult],
    *args: object,
    principal_scope: PrincipalScope,
    **kwargs: object,
) -> ScopedResult:
    try:
        return operation(
            *args,
            **kwargs,
            principal_scope=principal_scope,
        )
    except TypeError as exc:
        if "principal_scope" not in str(exc):
            raise
        return operation(*args, **kwargs)


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
        self._data_analysis = AuthorizedDataAnalysisInterface(
            interface.data_analysis,
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
    def data_analysis(self) -> DataAnalysisInterfaceProtocol:
        return self._data_analysis

    @property
    def skills(self) -> SkillInterfaceProtocol:
        return self._skills

    @property
    def sessions(self) -> SessionInterfaceProtocol:
        return self._sessions

    async def initialize(self) -> None:
        await self._interface.initialize()

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
        self._principal_scope = PrincipalScope.for_principal(principal)

    async def create_context(
        self,
        context: Context,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> Context:
        self._require("contexts", "create", context.context_id)
        return await _call_with_scope(
            self._inner.create_context,
            context.model_copy(update={"owner_id": self._principal.principal_id}),
            principal_scope=self._principal_scope,
        )

    async def get_context(
        self,
        context_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> Context:
        self._require("contexts", "get", context_id)
        return await _call_with_scope(
            self._inner.get_context,
            context_id,
            principal_scope=self._principal_scope,
        )

    async def append_context(
        self,
        context_id: str,
        message: Content,
        *,
        expected_revision: int | None = None,
        principal_scope: PrincipalScope | None = None,
    ) -> Context:
        self._require("contexts", "append", context_id)
        kwargs: dict[str, object] = {}
        if expected_revision is not None:
            kwargs["expected_revision"] = expected_revision
        return await _call_with_scope(
            self._inner.append_context,
            context_id,
            message,
            principal_scope=self._principal_scope,
            **kwargs,
        )

    async def replace_context(
        self,
        context: Context,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> Context:
        self._require("contexts", "replace", context.context_id)
        return await _call_with_scope(
            self._inner.replace_context,
            context.model_copy(update={"owner_id": self._principal.principal_id}),
            principal_scope=self._principal_scope,
        )

    async def list_contexts(
        self,
        *,
        cursor: str | None = None,
        limit: int | None = None,
        owner_id: str | None = None,
        principal_scope: PrincipalScope | None = None,
    ) -> list[Context]:
        self._require("contexts", "list")
        try:
            return await self._inner.list_contexts(
                cursor=cursor,
                limit=limit,
                owner_id=owner_id,
                principal_scope=self._principal_scope,
            )
        except TypeError as exc:
            if "unexpected keyword argument" not in str(exc):
                raise
            return await self._inner.list_contexts()

    async def delete_context(
        self,
        context_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None:
        self._require("contexts", "delete", context_id)
        await _call_with_scope(
            self._inner.delete_context,
            context_id,
            principal_scope=self._principal_scope,
        )

    async def create_memory(
        self,
        memory: MemoryItem,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> MemoryItem:
        self._require("memories", "create", memory.memory_id)
        return await _call_with_scope(
            self._inner.create_memory,
            memory.model_copy(update={"owner_id": self._principal.principal_id}),
            principal_scope=self._principal_scope,
        )

    async def get_memory(
        self,
        memory_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> MemoryItem:
        self._require("memories", "get", memory_id)
        return await _call_with_scope(
            self._inner.get_memory,
            memory_id,
            principal_scope=self._principal_scope,
        )

    async def replace_memory(
        self,
        memory: MemoryItem,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> MemoryItem:
        self._require("memories", "replace", memory.memory_id)
        return await _call_with_scope(
            self._inner.replace_memory,
            memory.model_copy(update={"owner_id": self._principal.principal_id}),
            principal_scope=self._principal_scope,
        )

    async def list_memories(
        self,
        *,
        cursor: str | None = None,
        limit: int | None = None,
        owner_id: str | None = None,
        query: MemoryQuery | None = None,
        principal_scope: PrincipalScope | None = None,
    ) -> list[MemoryItem]:
        self._require("memories", "list")
        try:
            return await self._inner.list_memories(
                cursor=cursor,
                limit=limit,
                owner_id=owner_id,
                query=query,
                principal_scope=self._principal_scope,
            )
        except TypeError as exc:
            if "unexpected keyword argument" not in str(exc):
                raise
            return await self._inner.list_memories()

    async def delete_memory(
        self,
        memory_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None:
        self._require("memories", "delete", memory_id)
        await _call_with_scope(
            self._inner.delete_memory,
            memory_id,
            principal_scope=self._principal_scope,
        )

    async def select_memories(
        self,
        query: MemoryQuery | None = None,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> MemorySelection:
        self._require("memories", "select")
        return await _call_with_scope(
            self._inner.select_memories,
            query,
            principal_scope=self._principal_scope,
        )

    async def chat(self, provider_id: str, request: ChatRequest) -> ChatResponse:
        self._require("chat", "create", provider_id)
        return await self._inner.chat(provider_id, request)

    async def organize_chat_request(
        self,
        context_id: str,
        *,
        model_id: str,
        messages: list[Content] | None = None,
        memory_query: MemoryQuery | None = None,
        skills: list[ChatSkill] | None = None,
        tools: list[ToolDefinition] | None = None,
        metadata: dict[str, object] | None = None,
        principal_scope: PrincipalScope | None = None,
    ) -> ChatRequest:
        self._require("contexts", "preview", context_id)
        return await self._inner.organize_chat_request(
            context_id,
            model_id=model_id,
            messages=messages,
            memory_query=memory_query,
            skills=skills,
            tools=tools,
            metadata=metadata,
            principal_scope=self._principal_scope,
        )

    async def chat_with_context(
        self,
        provider_id: str,
        context_id: str,
        *,
        model_id: str,
        messages: list[Content],
        retry_from_message_index: int | None = None,
        memory_query: MemoryQuery | None = None,
        skills: list[ChatSkill] | None = None,
        tools: list[ToolDefinition] | None = None,
        metadata: dict[str, object] | None = None,
        principal_scope: PrincipalScope | None = None,
    ) -> ChatResponse:
        self._require("chat", "create", context_id)
        return await self._inner.chat_with_context(
            provider_id,
            context_id,
            model_id=model_id,
            messages=messages,
            retry_from_message_index=retry_from_message_index,
            memory_query=memory_query,
            skills=skills,
            tools=tools,
            metadata=metadata,
            principal_scope=self._principal_scope,
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
        retry_from_message_index: int | None = None,
        memory_query: MemoryQuery | None = None,
        skills: list[ChatSkill] | None = None,
        tools: list[ToolDefinition] | None = None,
        metadata: dict[str, object] | None = None,
        principal_scope: PrincipalScope | None = None,
    ) -> ChatStreamProtocol:
        self._require("chat", "stream", context_id)
        return await self._inner.chat_stream_with_context(
            provider_id,
            context_id,
            model_id=model_id,
            messages=messages,
            retry_from_message_index=retry_from_message_index,
            memory_query=memory_query,
            skills=skills,
            tools=tools,
            metadata=metadata,
            principal_scope=self._principal_scope,
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

    async def list_providers(self) -> list[ProviderInfo]:
        self._require("providers", "list")
        return await self._inner.list_providers()

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


class AuthorizedDataAnalysisInterface(DataAnalysisInterfaceProtocol):
    def __init__(
        self,
        inner: DataAnalysisInterfaceProtocol,
        authorizer: AuthorizerProtocol,
        principal: Principal,
    ) -> None:
        self._inner = inner
        self._authorizer = authorizer
        self._principal = principal

    def list_data_sources(self) -> list[DataSourceDefinition]:
        self._require("data-analysis", "list")
        return self._inner.list_data_sources()

    def get_data_source(self, source_id: str) -> DataSourceDefinition:
        self._require("data-analysis", "get", source_id)
        return self._inner.get_data_source(source_id)

    def list_data_fields(self, source_id: str) -> list[DataFieldDefinition]:
        self._require("data-analysis", "list_fields", source_id)
        return self._inner.list_data_fields(source_id)

    def list_data_metrics(self, source_id: str) -> list[DataMetricDefinition]:
        self._require("data-analysis", "list_metrics", source_id)
        return self._inner.list_data_metrics(source_id)

    async def run_statistics(
        self,
        request: DataStatisticsRequest,
    ) -> DataStatisticsResult:
        self._require("data-analysis", "statistics", request.source_id)
        return await self._inner.run_statistics(request)

    async def analyze_data(
        self,
        request: DataAnalysisRequest,
    ) -> DataAnalysisResult:
        self._require("data-analysis", "analyze", request.source_id)
        return await self._inner.analyze_data(request)

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
        self._principal_scope = PrincipalScope.for_principal(principal)

    async def start(
        self,
        request: AgentRunRequest,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> AgentRunState:
        self._require("agent-runs", "create", request.context_id)
        return await _call_with_scope(
            self._inner.start,
            request.model_copy(update={"owner_id": self._principal.principal_id}),
            principal_scope=self._principal_scope,
        )

    async def resume(
        self,
        run_id: str,
        approvals: list[ToolApprovalDecision],
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> AgentRunState:
        self._require("agent-runs", "resume", run_id)
        return await _call_with_scope(
            self._inner.resume,
            run_id,
            approvals,
            principal_scope=self._principal_scope,
        )

    async def pause(
        self,
        run_id: str,
        *,
        reason: str | None = None,
        principal_scope: PrincipalScope | None = None,
    ) -> AgentRunState:
        self._require("agent-runs", "pause", run_id)
        return await _call_with_scope(
            self._inner.pause,
            run_id,
            reason=reason,
            principal_scope=self._principal_scope,
        )

    async def cancel(
        self,
        run_id: str,
        *,
        reason: str | None = None,
        principal_scope: PrincipalScope | None = None,
    ) -> AgentRunState:
        self._require("agent-runs", "cancel", run_id)
        return await _call_with_scope(
            self._inner.cancel,
            run_id,
            reason=reason,
            principal_scope=self._principal_scope,
        )

    def start_stream(
        self,
        request: AgentRunRequest,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> AgentTraceStreamProtocol:
        self._require("agent-runs", "stream", request.context_id)
        return _call_with_scope_sync(
            self._inner.start_stream,
            request.model_copy(update={"owner_id": self._principal.principal_id}),
            principal_scope=self._principal_scope,
        )

    def resume_stream(
        self,
        run_id: str,
        approvals: list[ToolApprovalDecision],
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> AgentTraceStreamProtocol:
        self._require("agent-runs", "resume_stream", run_id)
        return _call_with_scope_sync(
            self._inner.resume_stream,
            run_id,
            approvals,
            principal_scope=self._principal_scope,
        )

    def get_state(
        self,
        run_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> AgentRunState:
        self._require("agent-runs", "get", run_id)
        return _call_with_scope_sync(
            self._inner.get_state,
            run_id,
            principal_scope=self._principal_scope,
        )

    def list_states(
        self,
        *,
        cursor: str | None = None,
        limit: int | None = None,
        owner_id: str | None = None,
        status: AgentRunStatus | None = None,
        context_id: str | None = None,
        principal_scope: PrincipalScope | None = None,
    ) -> list[AgentRunState]:
        self._require("agent-runs", "list")
        try:
            return self._inner.list_states(
                cursor=cursor,
                limit=limit,
                owner_id=owner_id,
                status=status,
                context_id=context_id,
                principal_scope=self._principal_scope,
            )
        except TypeError as exc:
            if "unexpected keyword argument" not in str(exc):
                raise
            return self._inner.list_states()

    def list_trace(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
        limit: int | None = None,
        principal_scope: PrincipalScope | None = None,
    ) -> list[AgentTraceEvent]:
        self._require("agent-runs", "list_trace", run_id)
        return _call_with_scope_sync(
            self._inner.list_trace,
            run_id,
            after_sequence=after_sequence,
            limit=limit,
            principal_scope=self._principal_scope,
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
        self._principal_scope = PrincipalScope.for_principal(principal)

    async def create_session(
        self,
        session: Session,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> Session:
        self._require("sessions", "create", session.session_id)
        return await _call_with_scope(
            self._inner.create_session,
            session.model_copy(update={"owner_id": self._principal.principal_id}),
            principal_scope=self._principal_scope,
        )

    async def get_session(
        self,
        session_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> Session:
        self._require("sessions", "get", session_id)
        return await _call_with_scope(
            self._inner.get_session,
            session_id,
            principal_scope=self._principal_scope,
        )

    async def replace_session(
        self,
        session: Session,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> Session:
        self._require("sessions", "replace", session.session_id)
        return await _call_with_scope(
            self._inner.replace_session,
            session.model_copy(update={"owner_id": self._principal.principal_id}),
            principal_scope=self._principal_scope,
        )

    async def archive_session(
        self,
        session_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> Session:
        self._require("sessions", "archive", session_id)
        return await _call_with_scope(
            self._inner.archive_session,
            session_id,
            principal_scope=self._principal_scope,
        )

    async def list_sessions(
        self,
        *,
        cursor: str | None = None,
        limit: int | None = None,
        owner_id: str | None = None,
        status: SessionStatus | None = None,
        provider_id: str | None = None,
        model_id: str | None = None,
        principal_scope: PrincipalScope | None = None,
    ) -> list[Session]:
        self._require("sessions", "list")
        try:
            return await self._inner.list_sessions(
                cursor=cursor,
                limit=limit,
                owner_id=owner_id,
                status=status,
                provider_id=provider_id,
                model_id=model_id,
                principal_scope=self._principal_scope,
            )
        except TypeError as exc:
            if "unexpected keyword argument" not in str(exc):
                raise
            return await self._inner.list_sessions()

    async def delete_session(
        self,
        session_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None:
        self._require("sessions", "delete", session_id)
        await _call_with_scope(
            self._inner.delete_session,
            session_id,
            principal_scope=self._principal_scope,
        )

    async def chat_with_session(
        self,
        session_id: str,
        request: SessionChatRequest,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> SessionChatResult:
        self._require("sessions", "chat", session_id)
        return await _call_with_scope(
            self._inner.chat_with_session,
            session_id,
            request,
            principal_scope=self._principal_scope,
        )

    async def start_agent_run_for_session(
        self,
        session_id: str,
        request: SessionAgentRunRequest,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> AgentRunState:
        self._require("sessions", "start_agent_run", session_id)
        return await _call_with_scope(
            self._inner.start_agent_run_for_session,
            session_id,
            request,
            principal_scope=self._principal_scope,
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
