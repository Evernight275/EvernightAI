from EvernightAI.core.protocol.base import EvernightAIProtocol
from EvernightAI.core.protocol.agent import (
    AgentRunExecutorProtocol,
    AgentRunStateRegisterProtocol,
    AgentTraceRegisterProtocol,
)
from EvernightAI.core.protocol.context import (
    ContextManageProtocol,
    ContextOrganizerProtocol,
    ContextRegisterProtocol,
    ContextStrategyProtocol,
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
from EvernightAI.core.protocol.skill import SkillManageProtocol, SkillRegisterProtocol
from EvernightAI.core.protocol.tool import (
    ToolManageProtocol,
    ToolRegisterProtocol,
    ToolSafetyPolicyProtocol,
    ToolSourceProtocol,
)
from EvernightAI.core.schema.content import PromptCacheMode, PromptCacheScope


class RuntimeProtocol(EvernightAIProtocol):
    """
    运行时协议
    """

    @property
    def provider_factory(self) -> ProviderFactoryProtocol: ...

    @property
    def providers(self) -> ProviderManageProtocol: ...

    @property
    def provider_config_store(self) -> ProviderConfigStoreProtocol | None: ...

    @property
    def tool_register(self) -> ToolRegisterProtocol: ...

    @property
    def tools(self) -> ToolManageProtocol: ...

    @property
    def tool_safety_policy(self) -> ToolSafetyPolicyProtocol: ...

    @property
    def tool_sources(self) -> list[ToolSourceProtocol]: ...

    @property
    def sandbox(self) -> SandboxExecuteProtocol | None: ...

    @property
    def skill_register(self) -> SkillRegisterProtocol: ...

    @property
    def skills(self) -> SkillManageProtocol: ...

    @property
    def context_register(self) -> ContextRegisterProtocol: ...

    @property
    def contexts(self) -> ContextManageProtocol: ...

    @property
    def context_organizer(self) -> ContextOrganizerProtocol: ...

    @property
    def context_strategy(self) -> ContextStrategyProtocol: ...

    @property
    def prompt_cache_mode(self) -> PromptCacheMode: ...

    @property
    def prompt_cache_scope(self) -> PromptCacheScope: ...

    @property
    def data_analysis_register(self) -> DataAnalysisRegisterProtocol: ...

    @property
    def data_analysis(self) -> DataAnalysisManageProtocol: ...

    @property
    def memory_register(self) -> MemoryRegisterProtocol: ...

    @property
    def memories(self) -> MemoryManageProtocol: ...

    @property
    def memory_strategy(self) -> MemoryStrategyProtocol: ...

    @property
    def memory_write_strategy(self) -> MemoryWriteStrategyProtocol: ...

    @property
    def session_register(self) -> SessionRegisterProtocol: ...

    @property
    def sessions(self) -> SessionManageProtocol: ...

    @property
    def agent_state_register(self) -> AgentRunStateRegisterProtocol | None: ...

    @property
    def agent_run_executor(self) -> AgentRunExecutorProtocol | None: ...

    @property
    def agent_trace_register(self) -> AgentTraceRegisterProtocol | None: ...

    @property
    def is_ready(self) -> bool: ...

    async def initialize(self) -> None: ...

    async def close(self) -> None: ...
