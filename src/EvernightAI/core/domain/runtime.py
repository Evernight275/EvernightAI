import inspect
from typing import Any

from EvernightAI.core.protocol.agent import (
    AgentRunExecutorProtocol,
    AgentRunStateRegisterProtocol,
    AgentTraceRegisterProtocol,
    ToolExecutionRegisterProtocol,
)
from EvernightAI.core.protocol.context import (
    ContextManageProtocol,
    ContextOrganizerProtocol,
    ContextRegisterProtocol,
    ContextStrategyProtocol,
)
from EvernightAI.core.domain.data_analysis import (
    DataAnalysisManager,
    DataAnalysisRegister,
)
from EvernightAI.core.protocol.data_analysis import (
    DataAnalysisManageProtocol,
    DataAnalysisRegisterProtocol,
)
from EvernightAI.core.protocol.memory import (
    MemoryManageProtocol,
    MemoryRegisterProtocol,
    MemoryStrategyProtocol,
    MemoryWriteStrategyProtocol,
)
from EvernightAI.core.protocol.provider import (
    ProviderConfigStoreProtocol,
    ProviderFactoryProtocol,
    ProviderManageProtocol,
)
from EvernightAI.core.protocol.sandbox import SandboxExecuteProtocol
from EvernightAI.core.protocol.session import (
    SessionManageProtocol,
    SessionRegisterProtocol,
)
from EvernightAI.core.domain.session import SessionManager, SessionRegister
from EvernightAI.core.protocol.skill import SkillManageProtocol, SkillRegisterProtocol
from EvernightAI.core.protocol.tool import (
    ToolManageProtocol,
    ToolRegisterProtocol,
    ToolSafetyPolicyProtocol,
    ToolSourceProtocol,
)
from EvernightAI.core.protocol.runtime import RuntimeProtocol
from EvernightAI.core.schema.content import PromptCacheMode, PromptCacheScope
from EvernightAI.core.domain.skill import SkillManager, SkillRegister


class RuntimeKernel(RuntimeProtocol):
    def __init__(
        self,
        *,
        provider_factory: ProviderFactoryProtocol,
        providers: ProviderManageProtocol,
        provider_config_store: ProviderConfigStoreProtocol | None = None,
        tool_register: ToolRegisterProtocol,
        tools: ToolManageProtocol,
        tool_safety_policy: ToolSafetyPolicyProtocol,
        tool_sources: list[ToolSourceProtocol] | None = None,
        context_register: ContextRegisterProtocol,
        contexts: ContextManageProtocol,
        context_organizer: ContextOrganizerProtocol,
        context_strategy: ContextStrategyProtocol,
        prompt_cache_mode: PromptCacheMode = PromptCacheMode.PREFER_EXPLICIT,
        prompt_cache_scope: PromptCacheScope = PromptCacheScope.CONTEXT,
        memory_register: MemoryRegisterProtocol,
        memories: MemoryManageProtocol,
        memory_strategy: MemoryStrategyProtocol,
        memory_write_strategy: MemoryWriteStrategyProtocol,
        data_analysis_register: DataAnalysisRegisterProtocol | None = None,
        data_analysis: DataAnalysisManageProtocol | None = None,
        session_register: SessionRegisterProtocol | None = None,
        sessions: SessionManageProtocol | None = None,
        skill_register: SkillRegisterProtocol | None = None,
        skills: SkillManageProtocol | None = None,
        agent_state_register: AgentRunStateRegisterProtocol | None = None,
        agent_run_executor: AgentRunExecutorProtocol | None = None,
        agent_trace_register: AgentTraceRegisterProtocol | None = None,
        tool_execution_register: ToolExecutionRegisterProtocol | None = None,
        sandbox: SandboxExecuteProtocol | None = None,
    ) -> None:
        self._provider_factory = provider_factory
        self._providers = providers
        self._provider_config_store = provider_config_store
        self._initialized = False
        self._initialization_error: Exception | None = None
        self._tool_register = tool_register
        self._tools = tools
        self._tool_safety_policy = tool_safety_policy
        self._tool_sources = list(tool_sources or [])
        self._sandbox = sandbox
        self._skill_register = skill_register or SkillRegister()
        self._skills = skills or SkillManager(self._skill_register)
        self._context_register = context_register
        self._contexts = contexts
        self._context_organizer = context_organizer
        self._context_strategy = context_strategy
        self._prompt_cache_mode = prompt_cache_mode
        self._prompt_cache_scope = prompt_cache_scope
        self._data_analysis_register = data_analysis_register or DataAnalysisRegister()
        self._data_analysis = data_analysis or DataAnalysisManager(
            self._data_analysis_register
        )
        self._memory_register = memory_register
        self._memories = memories
        self._memory_strategy = memory_strategy
        self._memory_write_strategy = memory_write_strategy
        self._session_register = session_register or SessionRegister()
        self._sessions = sessions or SessionManager(self._session_register)
        self._agent_state_register = agent_state_register
        self._agent_run_executor = agent_run_executor
        self._agent_trace_register = agent_trace_register
        self._tool_execution_register = tool_execution_register

    @property
    def provider_factory(self) -> ProviderFactoryProtocol:
        return self._provider_factory

    @property
    def providers(self) -> ProviderManageProtocol:
        return self._providers

    @property
    def provider_config_store(self) -> ProviderConfigStoreProtocol | None:
        return self._provider_config_store

    @property
    def tool_register(self) -> ToolRegisterProtocol:
        return self._tool_register

    @property
    def tools(self) -> ToolManageProtocol:
        return self._tools

    @property
    def tool_safety_policy(self) -> ToolSafetyPolicyProtocol:
        return self._tool_safety_policy

    @property
    def tool_sources(self) -> list[ToolSourceProtocol]:
        return list(self._tool_sources)

    @property
    def sandbox(self) -> SandboxExecuteProtocol | None:
        return self._sandbox

    @property
    def skill_register(self) -> SkillRegisterProtocol:
        return self._skill_register

    @property
    def skills(self) -> SkillManageProtocol:
        return self._skills

    @property
    def context_register(self) -> ContextRegisterProtocol:
        return self._context_register

    @property
    def contexts(self) -> ContextManageProtocol:
        return self._contexts

    @property
    def context_organizer(self) -> ContextOrganizerProtocol:
        return self._context_organizer

    @property
    def context_strategy(self) -> ContextStrategyProtocol:
        return self._context_strategy

    @property
    def prompt_cache_mode(self) -> PromptCacheMode:
        return self._prompt_cache_mode

    @property
    def prompt_cache_scope(self) -> PromptCacheScope:
        return self._prompt_cache_scope

    @property
    def data_analysis_register(self) -> DataAnalysisRegisterProtocol:
        return self._data_analysis_register

    @property
    def data_analysis(self) -> DataAnalysisManageProtocol:
        return self._data_analysis

    @property
    def memory_register(self) -> MemoryRegisterProtocol:
        return self._memory_register

    @property
    def memories(self) -> MemoryManageProtocol:
        return self._memories

    @property
    def memory_strategy(self) -> MemoryStrategyProtocol:
        return self._memory_strategy

    @property
    def memory_write_strategy(self) -> MemoryWriteStrategyProtocol:
        return self._memory_write_strategy

    @property
    def session_register(self) -> SessionRegisterProtocol:
        return self._session_register

    @property
    def sessions(self) -> SessionManageProtocol:
        return self._sessions

    @property
    def agent_state_register(self) -> AgentRunStateRegisterProtocol | None:
        return self._agent_state_register

    @property
    def agent_run_executor(self) -> AgentRunExecutorProtocol | None:
        return self._agent_run_executor

    @property
    def agent_trace_register(self) -> AgentTraceRegisterProtocol | None:
        return self._agent_trace_register

    @property
    def tool_execution_register(self) -> ToolExecutionRegisterProtocol | None:
        return self._tool_execution_register

    @property
    def is_ready(self) -> bool:
        if not self._initialized or self._initialization_error is not None:
            return False
        if any(not source.is_ready() for source in self._tool_sources):
            return False
        for resource in self._persistent_resources():
            checker = getattr(resource, "is_ready", None)
            if callable(checker) and not checker():
                return False
        return True

    async def initialize(self) -> None:
        if self._initialized:
            return
        loaded_sources: list[ToolSourceProtocol] = []
        try:
            await self._providers.restore()
            for source in self._tool_sources:
                await source.load(self._tool_register)
                loaded_sources.append(source)
        except BaseException as exc:
            for source in reversed(loaded_sources):
                await source.close()
            if isinstance(exc, Exception):
                self._initialization_error = exc
            raise
        self._initialization_error = None
        self._initialized = True

    async def close(self) -> None:
        for source in reversed(self._tool_sources):
            await source.close()
        await self._providers.close()
        for resource in [*self._persistent_resources(), self._sandbox]:
            await _close_if_supported(resource)

    def _persistent_resources(self) -> list[Any]:
        return [
            self._provider_config_store,
            self._context_register,
            self._data_analysis_register,
            self._memory_register,
            self._session_register,
            self._agent_state_register,
            self._agent_trace_register,
            self._tool_execution_register,
        ]


async def _close_if_supported(resource: Any) -> None:
    if resource is None:
        return

    close = getattr(resource, "close", None)
    if not callable(close):
        return

    result = close()
    if inspect.isawaitable(result):
        await result
