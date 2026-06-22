from EvernightAI.core.protocol.base import EvernightAIProtocol
from EvernightAI.core.protocol.agent import (
    AgentRunStateRegisterProtocol,
    AgentTraceRegisterProtocol,
)
from EvernightAI.core.protocol.context import (
    ContextManageProtocol,
    ContextOrganizerProtocol,
    ContextRegisterProtocol,
    ContextStrategyProtocol,
)
from EvernightAI.core.protocol.memory import (
    MemoryManageProtocol,
    MemoryRegisterProtocol,
    MemoryStrategyProtocol,
    MemoryWriteStrategyProtocol,
)
from EvernightAI.core.protocol.provider import (
    ProviderFactoryProtocol,
    ProviderManageProtocol,
)
from EvernightAI.core.protocol.session import (
    SessionManageProtocol,
    SessionRegisterProtocol,
)
from EvernightAI.core.protocol.skill import SkillManageProtocol, SkillRegisterProtocol
from EvernightAI.core.protocol.tool import (
    ToolManageProtocol,
    ToolRegisterProtocol,
    ToolSafetyPolicyProtocol,
)


class RuntimeProtocol(EvernightAIProtocol):
    """
    运行时协议
    """

    @property
    def provider_factory(self) -> ProviderFactoryProtocol: ...

    @property
    def providers(self) -> ProviderManageProtocol: ...

    @property
    def tool_register(self) -> ToolRegisterProtocol: ...

    @property
    def tools(self) -> ToolManageProtocol: ...

    @property
    def tool_safety_policy(self) -> ToolSafetyPolicyProtocol: ...

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
    def agent_trace_register(self) -> AgentTraceRegisterProtocol | None: ...

    async def close(self) -> None: ...
