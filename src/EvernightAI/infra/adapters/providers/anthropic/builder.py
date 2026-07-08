from EvernightAI.core.protocol.provider import ProviderInstanceProtocol
from EvernightAI.core.schema.provider import ProviderConfig
from EvernightAI.infra.adapters.providers.anthropic.instance import AnthropicProviderInstance


async def build_anthropic_provider(
    config: ProviderConfig,
) -> ProviderInstanceProtocol:
    """创建 Anthropic 提供商实例"""
    return AnthropicProviderInstance(config)
