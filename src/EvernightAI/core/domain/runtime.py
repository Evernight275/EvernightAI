from EvernightAI.core.protocol.base import RuntimeProtocol
from EvernightAI.core.protocol.provider import (
    ProviderFactoryProtocol,
    ProviderManageProtocol,
)
from EvernightAI.core.protocol.tool import ToolManageProtocol, ToolRegisterProtocol


class RuntimeKernel(RuntimeProtocol):
    def __init__(
        self,
        *,
        provider_factory: ProviderFactoryProtocol,
        providers: ProviderManageProtocol,
        tool_register: ToolRegisterProtocol,
        tools: ToolManageProtocol,
    ) -> None:
        self._provider_factory = provider_factory
        self._providers = providers
        self._tool_register = tool_register
        self._tools = tools

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

    async def close(self) -> None:
        await self._providers.close()
