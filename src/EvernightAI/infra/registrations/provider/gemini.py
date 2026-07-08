from EvernightAI.core.protocol.provider import ProviderFactoryProtocol
from EvernightAI.core.schema.provider import ProviderType
from EvernightAI.infra.adapters.providers.gemini.builder import build_gemini_provider


def register_gemini_provider(factory: ProviderFactoryProtocol) -> None:
    """注册 Gemini 提供商构建器"""
    factory.register(ProviderType.GOOGLE, build_gemini_provider)
