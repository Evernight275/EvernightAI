from EvernightAI.core.protocol.context import (
    ContextManageProtocol,
    ContextOrganizerProtocol,
    ContextRegisterProtocol,
)
from EvernightAI.core.protocol.provider import (
    ProviderFactoryProtocol,
    ProviderManageProtocol,
)
from EvernightAI.core.protocol.tool import ToolManageProtocol, ToolRegisterProtocol
from EvernightAI.core.protocol.runtime import RuntimeProtocol


class RuntimeKernel(RuntimeProtocol):
    def __init__(
        self,
        *,
        provider_factory: ProviderFactoryProtocol,
        providers: ProviderManageProtocol,
        tool_register: ToolRegisterProtocol,
        tools: ToolManageProtocol,
        context_register: ContextRegisterProtocol,
        contexts: ContextManageProtocol,
        context_organizer: ContextOrganizerProtocol,
    ) -> None:
        self._provider_factory = provider_factory
        self._providers = providers
        self._tool_register = tool_register
        self._tools = tools
        self._context_register = context_register
        self._contexts = contexts
        self._context_organizer = context_organizer

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
    def context_register(self) -> ContextRegisterProtocol:
        return self._context_register

    @property
    def contexts(self) -> ContextManageProtocol:
        return self._contexts

    @property
    def context_organizer(self) -> ContextOrganizerProtocol:
        return self._context_organizer

    async def close(self) -> None:
        await self._providers.close()
