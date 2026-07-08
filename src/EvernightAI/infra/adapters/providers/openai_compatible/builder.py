from EvernightAI.core.protocol.provider import ProviderInstanceProtocol
from EvernightAI.core.schema.provider import ProviderConfig
from EvernightAI.infra.adapters.providers.openai_compatible.instance import (
    OpenAICompatibleProviderInstance,
)


async def build_openai_compatible_provider(
    config: ProviderConfig,
) -> ProviderInstanceProtocol:
    """创建 OpenAI-compatible 提供商实例"""
    return OpenAICompatibleProviderInstance(config)
