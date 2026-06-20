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
)
from EvernightAI.core.protocol.provider import (
    ProviderFactoryProtocol,
    ProviderManageProtocol,
)
from EvernightAI.core.protocol.tool import (
    ToolManageProtocol,
    ToolRegisterProtocol,
    ToolSafetyPolicyProtocol,
)
from EvernightAI.core.protocol.runtime import RuntimeProtocol


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
    ) -> None:
        self._provider_factory = provider_factory
        self._providers = providers
        self._tool_register = tool_register
        self._tools = tools
        self._tool_safety_policy = tool_safety_policy
        self._context_register = context_register
        self._contexts = contexts
        self._context_organizer = context_organizer
        self._context_strategy = context_strategy
        self._memory_register = memory_register
        self._memories = memories
        self._memory_strategy = memory_strategy

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

    async def close(self) -> None:
        await self._providers.close()
