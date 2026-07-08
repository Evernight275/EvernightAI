from EvernightAI.core.protocol.provider import ProviderFactoryProtocol
from EvernightAI.core.schema.provider import ProviderType
from EvernightAI.infra.adapters.providers.openai_responses.builder import (
    build_openai_responses_provider,
)


def register_openai_responses_provider(factory: ProviderFactoryProtocol) -> None:
    """注册 OpenAI Responses 提供商构建器"""
    factory.register(ProviderType.OPENAI_RESPONSES, build_openai_responses_provider)
