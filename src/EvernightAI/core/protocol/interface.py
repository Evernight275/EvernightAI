from typing import Protocol, runtime_checkable

from EvernightAI.core.protocol.base import EvernightAIProtocol
from EvernightAI.core.protocol.provider import ProviderInstanceProtocol
from EvernightAI.core.protocol.runtime import RuntimeProtocol
from EvernightAI.core.protocol.stream import AgentTraceStreamProtocol, SSEProtocol
from EvernightAI.core.schema.agent import (
    AgentRunRequest,
    AgentRunResult,
    AgentRunState,
    AgentTraceEvent,
)
from EvernightAI.core.schema.content import ChatRequest, ChatResponse, Content
from EvernightAI.core.schema.context import Context
from EvernightAI.core.schema.memory import MemoryItem, MemoryQuery, MemorySelection
from EvernightAI.core.schema.provider import ProviderConfig
from EvernightAI.core.schema.skill import SkillCall, SkillDefinition, SkillResult
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
        memory_query: MemoryQuery | None = None,
        tools: list[ToolDefinition] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> ChatResponse: ...

    async def chat_stream(
        self, provider_id: str, request: ChatRequest
    ) -> SSEProtocol: ...

    async def close(self) -> None: ...


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

    def list_trace(self, run_id: str) -> list[AgentTraceEvent]: ...


class SkillInterfaceProtocol(InterfaceProtocol):
    def list_skills(self) -> list[SkillDefinition]: ...

    async def execute_skill(self, call: SkillCall) -> SkillResult: ...


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
    def skills(self) -> SkillInterfaceProtocol: ...

    async def close(self) -> None: ...
