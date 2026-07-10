from typing import Protocol, runtime_checkable

from EvernightAI.core.protocol.base import EvernightAIProtocol
from EvernightAI.core.protocol.provider import ProviderInstanceProtocol
from EvernightAI.core.protocol.runtime import RuntimeProtocol
from EvernightAI.core.protocol.stream import (
    AgentTraceStreamProtocol,
    ChatStreamProtocol,
)
from EvernightAI.core.schema.agent import (
    AgentRunRequest,
    AgentRunResult,
    AgentRunState,
    AgentTraceEvent,
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
from EvernightAI.core.schema.provider import ProviderConfig
from EvernightAI.core.schema.provider import (
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
    SkillRenderRequest,
    SkillCapability,
    SkillDefinition,
)
from EvernightAI.core.schema.tool import ToolApprovalDecision, ToolDefinition


class InterfaceProtocol(EvernightAIProtocol): ...


class ChatInterfaceProtocol(InterfaceProtocol):
    async def create_provider(
        self,
        config: ProviderConfig,
    ) -> ProviderInstanceProtocol: ...

    async def create_context(self, context: Context) -> Context: ...

    async def get_context(self, context_id: str) -> Context: ...

    async def append_context(self, context_id: str, message: Content) -> Context: ...

    async def replace_context(self, context: Context) -> Context: ...

    async def list_contexts(self) -> list[Context]: ...

    async def delete_context(self, context_id: str) -> None: ...

    async def create_memory(self, memory: MemoryItem) -> MemoryItem: ...

    async def get_memory(self, memory_id: str) -> MemoryItem: ...

    async def list_memories(self) -> list[MemoryItem]: ...

    async def delete_memory(self, memory_id: str) -> None: ...

    async def select_memories(
        self,
        query: MemoryQuery | None = None,
    ) -> MemorySelection: ...

    async def chat(self, provider_id: str, request: ChatRequest) -> ChatResponse: ...

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
    ) -> ChatResponse: ...

    async def chat_stream(
        self, provider_id: str, request: ChatRequest
    ) -> ChatStreamProtocol: ...

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
    ) -> ChatStreamProtocol: ...

    async def close(self) -> None: ...


class ProviderInterfaceProtocol(InterfaceProtocol):
    async def create_provider(self, config: ProviderConfig) -> ProviderInfo: ...

    async def list_providers(self) -> list[ProviderInfo]: ...

    async def list_provider_models(
        self,
        provider_id: str,
    ) -> list[ProviderModelConfig]: ...

    async def get_provider_model(
        self,
        provider_id: str,
        model_id: str,
    ) -> ProviderModelConfig: ...

    async def provider_supports(
        self,
        provider_id: str,
        capability: ProviderModelCapability,
    ) -> bool: ...

    async def delete_provider(self, provider_id: str) -> None: ...


class ToolInterfaceProtocol(InterfaceProtocol):
    def list_tools(self) -> list[ToolDefinition]: ...


class DataAnalysisInterfaceProtocol(InterfaceProtocol):
    def list_data_sources(self) -> list[DataSourceDefinition]: ...

    def get_data_source(self, source_id: str) -> DataSourceDefinition: ...

    def list_data_fields(self, source_id: str) -> list[DataFieldDefinition]: ...

    def list_data_metrics(self, source_id: str) -> list[DataMetricDefinition]: ...

    async def run_statistics(
        self,
        request: DataStatisticsRequest,
    ) -> DataStatisticsResult: ...

    async def analyze_data(
        self,
        request: DataAnalysisRequest,
    ) -> DataAnalysisResult: ...


class AgentInterfaceProtocol(InterfaceProtocol):
    async def run_agent(self, request: AgentRunRequest) -> AgentRunResult: ...

    async def run_agent_until_pause(
        self, request: AgentRunRequest
    ) -> AgentRunState: ...

    async def resume_agent(
        self,
        state: AgentRunState,
        approvals: list[ToolApprovalDecision],
    ) -> AgentRunResult: ...

    async def resume_agent_until_pause(
        self,
        state: AgentRunState,
        approvals: list[ToolApprovalDecision],
    ) -> AgentRunState: ...

    async def start_agent_run(self, request: AgentRunRequest) -> AgentRunState: ...

    async def resume_agent_run(
        self,
        run_id: str,
        approvals: list[ToolApprovalDecision],
    ) -> AgentRunState: ...

    def run_agent_stream(
        self,
        request: AgentRunRequest,
    ) -> AgentTraceStreamProtocol: ...

    def resume_agent_stream(
        self,
        state: AgentRunState,
        approvals: list[ToolApprovalDecision],
    ) -> AgentTraceStreamProtocol: ...

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
    ) -> ChatResponse: ...


class AgentRunInterfaceProtocol(InterfaceProtocol):
    async def start(self, request: AgentRunRequest) -> AgentRunState: ...

    async def resume(
        self,
        run_id: str,
        approvals: list[ToolApprovalDecision],
    ) -> AgentRunState: ...

    async def pause(
        self,
        run_id: str,
        *,
        reason: str | None = None,
    ) -> AgentRunState: ...

    async def cancel(
        self,
        run_id: str,
        *,
        reason: str | None = None,
    ) -> AgentRunState: ...

    def start_stream(
        self,
        request: AgentRunRequest,
    ) -> AgentTraceStreamProtocol: ...

    def resume_stream(
        self,
        run_id: str,
        approvals: list[ToolApprovalDecision],
    ) -> AgentTraceStreamProtocol: ...

    def get_state(self, run_id: str) -> AgentRunState: ...

    def list_states(self) -> list[AgentRunState]: ...

    def list_trace(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
        limit: int | None = None,
    ) -> list[AgentTraceEvent]: ...

    async def close(self) -> None: ...


class SkillInterfaceProtocol(InterfaceProtocol):
    def list_skills(self) -> list[SkillDefinition]: ...

    def get_skill(self, skill_name: str) -> SkillDefinition: ...

    def skill_supports(self, skill_name: str, capability: SkillCapability) -> bool: ...

    async def render_skill(self, request: SkillRenderRequest) -> RenderedSkill: ...


class SessionInterfaceProtocol(InterfaceProtocol):
    async def create_session(self, session: Session) -> Session: ...

    async def get_session(self, session_id: str) -> Session: ...

    async def replace_session(self, session: Session) -> Session: ...

    async def archive_session(self, session_id: str) -> Session: ...

    async def list_sessions(self) -> list[Session]: ...

    async def delete_session(self, session_id: str) -> None: ...

    async def chat_with_session(
        self,
        session_id: str,
        request: SessionChatRequest,
    ) -> SessionChatResult: ...

    async def start_agent_run_for_session(
        self,
        session_id: str,
        request: SessionAgentRunRequest,
    ) -> AgentRunState: ...


class EvernightInterfaceProtocol(InterfaceProtocol):
    @property
    def runtime(self) -> RuntimeProtocol: ...

    @property
    def chat(self) -> ChatInterfaceProtocol: ...

    @property
    def agent(self) -> AgentInterfaceProtocol: ...

    @property
    def agent_runs(self) -> AgentRunInterfaceProtocol: ...

    @property
    def providers(self) -> ProviderInterfaceProtocol: ...

    @property
    def tools(self) -> ToolInterfaceProtocol: ...

    @property
    def data_analysis(self) -> DataAnalysisInterfaceProtocol: ...

    @property
    def skills(self) -> SkillInterfaceProtocol: ...

    @property
    def sessions(self) -> SessionInterfaceProtocol: ...

    async def close(self) -> None: ...
