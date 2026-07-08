from EvernightAI.core.protocol.provider import ProviderFactoryProtocol
from EvernightAI.core.schema.provider import ProviderType
from EvernightAI.infra.adapters.providers.openai_compatible.builder import (
    build_openai_compatible_provider,
)


def register_openai_compatible_provider(factory: ProviderFactoryProtocol) -> None:
    """注册 OpenAI-compatible 提供商构建器"""
    factory.register(ProviderType.OPENAI, build_openai_compatible_provider)
