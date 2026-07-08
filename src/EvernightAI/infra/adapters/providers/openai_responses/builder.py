from EvernightAI.core.protocol.provider import ProviderInstanceProtocol
from EvernightAI.core.schema.provider import ProviderConfig
from EvernightAI.infra.adapters.providers.openai_responses.instance import (
    OpenAIResponsesProviderInstance,
)


async def build_openai_responses_provider(
    config: ProviderConfig,
) -> ProviderInstanceProtocol:
    """创建 OpenAI Responses 提供商实例"""
    return OpenAIResponsesProviderInstance(config)
