from EvernightAI.core.domain.provider import ProviderFactory, ProviderManager
from EvernightAI.core.domain.tool import ToolManager, ToolRegister
from EvernightAI.core.protocol.base import RuntimeProtocol
from EvernightAI.core.protocol.provider import (
    ProviderFactoryProtocol,
    ProviderManageProtocol,
)
from EvernightAI.core.protocol.tool import ToolManageProtocol, ToolRegisterProtocol
from EvernightAI.infra.registrations.provider.openai_compatible import (
    register_openai_compatible_provider,
)
from EvernightAI.core.domain.runtime import RuntimeKernel


def create_provider_factory() -> ProviderFactory:
    factory = ProviderFactory()
    register_openai_compatible_provider(factory)
    return factory


def create_provider_manager() -> ProviderManager:
    return ProviderManager(create_provider_factory())


def create_tool_register() -> ToolRegister:
    return ToolRegister()


def create_tool_manager(register: ToolRegisterProtocol | None = None) -> ToolManager:
    return ToolManager(register or create_tool_register())


def create_runtime() -> RuntimeKernel:
    provider_factory = create_provider_factory()
    providers = ProviderManager(provider_factory)
    tool_register = create_tool_register()
    tools = ToolManager(tool_register)

    return RuntimeKernel(
        provider_factory=provider_factory,
        providers=providers,
        tool_register=tool_register,
        tools=tools,
    )
