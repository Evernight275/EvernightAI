import inspect
from typing import Any

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
from EvernightAI.core.domain.session import SessionManager, SessionRegister
from EvernightAI.core.protocol.skill import SkillManageProtocol, SkillRegisterProtocol
from EvernightAI.core.protocol.tool import (
    ToolManageProtocol,
    ToolRegisterProtocol,
    ToolSafetyPolicyProtocol,
)
from EvernightAI.core.protocol.runtime import RuntimeProtocol
from EvernightAI.core.domain.skill import SkillManager, SkillRegister


class RuntimeKernel(RuntimeProtocol):
    def __init__(
        self,
        *,
        provider_factory: ProviderFactoryProtocol,
        providers: ProviderManageProtocol,
        tool_register: ToolRegisterProtocol,
        tools: ToolManageProtocol,
        tool_safety_policy: ToolSafetyPolicyProtocol,
        context_register: ContextRegisterProtocol,
        contexts: ContextManageProtocol,
        context_organizer: ContextOrganizerProtocol,
        context_strategy: ContextStrategyProtocol,
        memory_register: MemoryRegisterProtocol,
        memories: MemoryManageProtocol,
        memory_strategy: MemoryStrategyProtocol,
        memory_write_strategy: MemoryWriteStrategyProtocol,
        session_register: SessionRegisterProtocol | None = None,
        sessions: SessionManageProtocol | None = None,
        skill_register: SkillRegisterProtocol | None = None,
        skills: SkillManageProtocol | None = None,
        agent_state_register: AgentRunStateRegisterProtocol | None = None,
        agent_trace_register: AgentTraceRegisterProtocol | None = None,
    ) -> None:
        self._provider_factory = provider_factory
        self._providers = providers
        self._tool_register = tool_register
        self._tools = tools
        self._tool_safety_policy = tool_safety_policy
        self._skill_register = skill_register or SkillRegister()
        self._skills = skills or SkillManager(self._skill_register)
        self._context_register = context_register
        self._contexts = contexts
        self._context_organizer = context_organizer
        self._context_strategy = context_strategy
        self._memory_register = memory_register
        self._memories = memories
        self._memory_strategy = memory_strategy
        self._memory_write_strategy = memory_write_strategy
        self._session_register = session_register or SessionRegister()
        self._sessions = sessions or SessionManager(self._session_register)
        self._agent_state_register = agent_state_register
        self._agent_trace_register = agent_trace_register

    @property
    def provider_factory(self) -> ProviderFactoryProtocol:
        return self._provider_factory

    @property
    def providers(self) -> ProviderManageProtocol:
        return self._providers

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
    def agent_trace_register(self) -> AgentTraceRegisterProtocol | None:
        return self._agent_trace_register

    async def close(self) -> None:
        await self._providers.close()
        for resource in [
            self._context_register,
            self._memory_register,
            self._session_register,
            self._agent_state_register,
            self._agent_trace_register,
        ]:
            await _close_if_supported(resource)


async def _close_if_supported(resource: Any) -> None:
    if resource is None:
        return

    close = getattr(resource, "close", None)
    if not callable(close):
        return

    result = close()
    if inspect.isawaitable(result):
        await result
