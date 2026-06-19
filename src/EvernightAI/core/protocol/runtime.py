from EvernightAI.core.protocol.base import EvernightAIProtocol
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
    def context_register(self) -> ContextRegisterProtocol: ...

    @property
    def contexts(self) -> ContextManageProtocol: ...

    @property
    def context_organizer(self) -> ContextOrganizerProtocol: ...

    async def close(self) -> None: ...
