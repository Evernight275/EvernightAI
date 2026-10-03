import asyncio
from EvernightAI.application.image import ImageApplication
from EvernightAI.core.schema.auth import PrincipalScope
from time import perf_counter

from EvernightAI.core.error.provider import (
    ProviderAuthorizationError,
    ProviderDisabledError,
    ProviderError,
    ProviderNotFoundError,
    ProviderRateLimitError,
    ProviderRequestError,
    ProviderRequestTimeoutError,
    ProviderUnavailableError,
)
from EvernightAI.core.schema.content import (
    ChatRequest,
    Content,
    ContentPart,
    ContentPartType,
    MessageRole,
)
from EvernightAI.core.protocol.interface import ProviderInterfaceProtocol
from EvernightAI.core.protocol.runtime import RuntimeProtocol
from EvernightAI.core.schema.image import (
    ImageEditRequest,
    ImageGenerationRecord,
    ImageGenerationRequest,
    ImageGenerationResponse,
    ImageHistoryPage,
)
from EvernightAI.core.schema.provider import (
    ProviderConfig,
    ProviderConfigUpdate,
    ProviderConfigView,
    ProviderTestRequest,
    ProviderTestResult,
    ProviderInfo,
    ProviderModelCapability,
    ProviderModelConfig,
)


PROVIDER_TEST_TIMEOUT_SECONDS = 30.0


class ProviderApplication(ProviderInterfaceProtocol):
    def __init__(self, runtime: RuntimeProtocol) -> None:
        self._runtime = runtime

    async def generate_images(
        self,
        provider_id: str,
        request: ImageGenerationRequest,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> ImageGenerationResponse:
        return await ImageApplication(self._runtime).generate(
            provider_id, request, principal_scope=principal_scope
        )

    async def edit_images(
        self,
        provider_id: str,
        request: ImageEditRequest,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> ImageGenerationResponse:
        return await ImageApplication(self._runtime).edit(
            provider_id, request, principal_scope=principal_scope
        )

    def list_image_records(
        self,
        *,
        limit: int = 20,
        cursor: str | None = None,
        principal_scope: PrincipalScope | None = None,
    ) -> ImageHistoryPage:
        return ImageApplication(self._runtime).list_records(
            limit=limit, cursor=cursor, principal_scope=principal_scope
        )

    def get_image_record(
        self, record_id: str, *, principal_scope: PrincipalScope | None = None
    ) -> ImageGenerationRecord:
        return ImageApplication(self._runtime).get_record(
            record_id, principal_scope=principal_scope
        )

    def delete_image_record(
        self, record_id: str, *, principal_scope: PrincipalScope | None = None
    ) -> None:
        ImageApplication(self._runtime).delete_record(
            record_id, principal_scope=principal_scope
        )

    async def create_provider(self, config: ProviderConfig) -> ProviderInfo:
        await self._runtime.providers.create(config, replace_existing=False)
        return await self._runtime.providers.get_info(config.provider_id)

    async def list_providers(self) -> list[ProviderInfo]:
        return await self._runtime.providers.list_infos()

    async def test_provider(
        self,
        provider_id: str,
        request: ProviderTestRequest,
    ) -> ProviderTestResult:
        await self._runtime.providers.get(provider_id)
        started = perf_counter()
        response_model_id = None
        error_type = None
        error_message = None
        try:
            async with asyncio.timeout(PROVIDER_TEST_TIMEOUT_SECONDS):
                response = await self._runtime.providers.chat(
                    provider_id,
                    ChatRequest(
                        model_id=request.model_id,
                        messages=[
                            Content(
                                role=MessageRole.USER,
                                content=[
                                    ContentPart(
                                        type=ContentPartType.TEXT, text="Reply with OK."
                                    ),
                                ],
                            )
                        ],
                    ),
                )
            response_model_id = response.model_id
        except ProviderDisabledError:
            raise
        except TimeoutError:
            error_type = "ProviderRequestTimeoutError"
            error_message = "The connection test exceeded its time limit."
        except ProviderError as error:
            error_type = error.error_type
            error_message = _test_error_message(error)
        return ProviderTestResult(
            provider_id=provider_id,
            model_id=request.model_id,
            success=error_type is None,
            elapsed_ms=round((perf_counter() - started) * 1000, 2),
            response_model_id=response_model_id,
            error_type=error_type,
            error_message=error_message,
        )

    async def get_provider_config(self, provider_id: str) -> ProviderConfigView:
        return await self._runtime.providers.get_config(provider_id)

    async def update_provider(
        self,
        provider_id: str,
        update: ProviderConfigUpdate,
    ) -> ProviderInfo:
        await self._runtime.providers.update(provider_id, update)
        return await self._runtime.providers.get_info(provider_id)

    async def list_provider_models(
        self,
        provider_id: str,
    ) -> list[ProviderModelConfig]:
        return await self._runtime.providers.list_models(provider_id)

    async def get_provider_model(
        self,
        provider_id: str,
        model_id: str,
    ) -> ProviderModelConfig:
        return await self._runtime.providers.get_model(provider_id, model_id)

    async def provider_supports(
        self,
        provider_id: str,
        capability: ProviderModelCapability,
    ) -> bool:
        return await self._runtime.providers.supports(provider_id, capability)

    async def delete_provider(self, provider_id: str) -> None:
        await self._runtime.providers.delete(provider_id)


def _test_error_message(error: ProviderError) -> str:
    if isinstance(error, ProviderAuthorizationError):
        return "The upstream service rejected the provider credentials."
    if isinstance(error, ProviderRequestTimeoutError):
        return "The upstream model request timed out."
    if isinstance(error, ProviderRateLimitError):
        return "The upstream service rate limit or quota was reached."
    if isinstance(error, ProviderNotFoundError):
        return "The requested model or upstream resource was not found."
    if isinstance(error, ProviderUnavailableError):
        return "The upstream service could not be reached or is unavailable."
    if isinstance(error, ProviderRequestError):
        return "The upstream service rejected the model request. Check model access and API compatibility."
    return "The provider could not complete the test. Check the saved configuration and API compatibility."
