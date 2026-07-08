from EvernightAI.core.protocol.provider import ProviderInstanceProtocol
from EvernightAI.core.schema.provider import ProviderConfig
from EvernightAI.infra.adapters.providers.gemini.instance import GeminiProviderInstance


async def build_gemini_provider(
    config: ProviderConfig,
) -> ProviderInstanceProtocol:
    """创建 Gemini 提供商实例"""
    return GeminiProviderInstance(config)
