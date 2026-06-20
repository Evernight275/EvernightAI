from pathlib import Path

from EvernightAI.core.domain.context import (
    BasicContextStrategy,
    ContextManager,
    ContextOrganizer,
    ContextRegister,
)
from EvernightAI.core.domain.memory import (
    BasicMemoryStrategy,
    BasicMemoryWriteStrategy,
    MemoryManager,
    MemoryRegister,
)
from EvernightAI.core.domain.provider import ProviderFactory, ProviderManager
from EvernightAI.core.domain.tool import (
    BasicToolSafetyPolicy,
    ToolManager,
    ToolRegister,
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
from EvernightAI.core.protocol.runtime import RuntimeProtocol
from EvernightAI.core.protocol.tool import (
    ToolManageProtocol,
    ToolRegisterProtocol,
    ToolSafetyPolicyProtocol,
)
from EvernightAI.infra.adapters.context.sqlite import SQLiteContextRegister
from EvernightAI.infra.registrations.provider.anthropic import (
    register_anthropic_provider,
)
from EvernightAI.infra.registrations.provider.gemini import register_gemini_provider
from EvernightAI.infra.registrations.provider.openai_compatible import (
    register_openai_compatible_provider,
)
from EvernightAI.infra.registrations.provider.openai_responses import (
    register_openai_responses_provider,
)
from EvernightAI.core.domain.runtime import RuntimeKernel


def create_provider_factory() -> ProviderFactory:
    factory = ProviderFactory()
    register_openai_compatible_provider(factory)
    register_openai_responses_provider(factory)
    register_gemini_provider(factory)
    register_anthropic_provider(factory)
    return factory


def create_provider_manager() -> ProviderManager:
    return ProviderManager(create_provider_factory())


def create_tool_register() -> ToolRegister:
    return ToolRegister()


def create_tool_safety_policy() -> BasicToolSafetyPolicy:
    return BasicToolSafetyPolicy()


def create_tool_manager(
    register: ToolRegisterProtocol | None = None,
    safety_policy: ToolSafetyPolicyProtocol | None = None,
) -> ToolManager:
    return ToolManager(
        register or create_tool_register(),
        safety_policy or create_tool_safety_policy(),
    )


def create_context_register() -> ContextRegister:
    return ContextRegister()


def create_context_manager(
    register: ContextRegisterProtocol | None = None,
) -> ContextManager:
    return ContextManager(register or create_context_register())


def create_context_organizer() -> ContextOrganizer:
    return ContextOrganizer()


def create_context_strategy(
    organizer: ContextOrganizerProtocol | None = None,
) -> BasicContextStrategy:
    return BasicContextStrategy(organizer or create_context_organizer())


def create_memory_register() -> MemoryRegister:
    return MemoryRegister()


def create_memory_manager(
    register: MemoryRegisterProtocol | None = None,
) -> MemoryManager:
    return MemoryManager(register or create_memory_register())


def create_memory_strategy() -> BasicMemoryStrategy:
    return BasicMemoryStrategy()


def create_memory_write_strategy() -> BasicMemoryWriteStrategy:
    return BasicMemoryWriteStrategy()


def create_sqlite_context_register(database_path: str | Path) -> SQLiteContextRegister:
    return SQLiteContextRegister(database_path)


def create_sqlite_context_manager(database_path: str | Path) -> ContextManager:
    return ContextManager(create_sqlite_context_register(database_path))


def create_runtime() -> RuntimeKernel:
    provider_factory = create_provider_factory()
    providers = ProviderManager(provider_factory)
    tool_register = create_tool_register()
    tool_safety_policy = create_tool_safety_policy()
    tools = ToolManager(tool_register, tool_safety_policy)
    context_register = create_context_register()
    contexts = ContextManager(context_register)
    context_organizer = create_context_organizer()
    context_strategy = create_context_strategy(context_organizer)
    memory_register = create_memory_register()
    memories = MemoryManager(memory_register)
    memory_strategy = create_memory_strategy()
    memory_write_strategy = create_memory_write_strategy()

    return RuntimeKernel(
        provider_factory=provider_factory,
        providers=providers,
        tool_register=tool_register,
        tools=tools,
        tool_safety_policy=tool_safety_policy,
        context_register=context_register,
        contexts=contexts,
        context_organizer=context_organizer,
        context_strategy=context_strategy,
        memory_register=memory_register,
        memories=memories,
        memory_strategy=memory_strategy,
        memory_write_strategy=memory_write_strategy,
    )
