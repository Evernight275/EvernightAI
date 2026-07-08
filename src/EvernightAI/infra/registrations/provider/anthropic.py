from EvernightAI.core.protocol.provider import ProviderFactoryProtocol
from EvernightAI.core.schema.provider import ProviderType
from EvernightAI.infra.adapters.providers.anthropic.builder import build_anthropic_provider


def register_anthropic_provider(factory: ProviderFactoryProtocol) -> None:
    """注册 Anthropic 提供商构建器"""
    factory.register(ProviderType.ANTHROPIC, build_anthropic_provider)
