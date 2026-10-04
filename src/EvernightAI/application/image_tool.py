import asyncio
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from pydantic import ValidationError

from EvernightAI.application.image import ImageApplication
from EvernightAI.application.image_task import ImageTaskApplication
from EvernightAI.core.error.tool import ToolInputError, ToolExecutionError
from EvernightAI.core.error.image import ImageTaskNotFoundError
from EvernightAI.core.protocol.runtime import RuntimeProtocol
from EvernightAI.core.schema.auth import PrincipalScope
from EvernightAI.core.schema.image import (
    ImageEditInput,
    ImageEditRequest,
    ImageGenerationRequest,
)
from EvernightAI.core.schema.image_task import ImageTaskSubmit
from EvernightAI.core.schema.image_tool import ImageToolRequest
from EvernightAI.core.schema.provider import ProviderModelCapability, ProviderType


class ImageToolApplication:
    def __init__(self, runtime: RuntimeProtocol) -> None:
        self._runtime = runtime

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        values = dict(arguments)
        context = values.pop("_execution_context", None)
        key = values.pop("_idempotency_key", None)
        if not isinstance(context, dict) or not context.get("tool_call_id"):
            raise ToolInputError("Image tools require a tool execution context")
        try:
            request = ImageToolRequest.model_validate(values)
        except ValidationError as exc:
            raise ToolInputError("Invalid image tool parameters", cause=exc) from exc
        scope = PrincipalScope(owner_id=context.get("owner_id"))
        session_id = context.get("session_id")
        if session_id is not None and not isinstance(session_id, str):
            raise ToolInputError("Invalid image tool session")
        identity = key or f"{context.get('run_id', '')}:{context['tool_call_id']}"
        task_id = uuid5(
            NAMESPACE_URL, f"EvernightAI:image-tool:{scope.owner_id}:{identity}"
        ).hex
        try:
            previous = self._runtime.image_tasks.get(task_id, principal_scope=scope)
        except ImageTaskNotFoundError:
            previous = None
        records = [
            ImageApplication(self._runtime).get_record(
                reference.record_id, principal_scope=scope
            )
            for reference in request.references
        ]
        source = previous or (records[0] if records else None)
        provider_id = request.provider_id or (source.provider_id if source else None)
        model_id = request.model_id
        if model_id is None and source and provider_id == source.provider_id:
            model_id = source.request.model_id
        provider_id, model_id = await self._select_model(provider_id, model_id)
        images: list[ImageEditInput] = []
        for reference, record in zip(request.references, records, strict=True):
            if reference.image_index >= len(record.response.images):
                raise ToolInputError("Reference image index is out of range")
            image = record.response.images[reference.image_index]
            if image.base64_data is None or image.mime_type is None:
                raise ToolInputError(
                    "The reference image is not archived. Download or archive it before editing."
                )
            images.append(
                ImageEditInput(base64_data=image.base64_data, mime_type=image.mime_type)
            )
        parameters = request.model_dump(
            exclude={"provider_id", "model_id", "references"}, exclude_none=True
        )
        if previous is not None:
            for name in ("quality", "output_format", "timeout_seconds"):
                if name not in values:
                    parameters[name] = getattr(previous.request, name)
        image_request = (
            ImageEditRequest(model_id=model_id, images=images, **parameters)
            if images
            else ImageGenerationRequest(model_id=model_id, **parameters)
        )
        app = ImageTaskApplication(self._runtime)
        task = await app.submit(
            ImageTaskSubmit(
                task_id=task_id,
                provider_id=provider_id,
                request=image_request,
                session_id=session_id,
            ),
            principal_scope=scope,
        )
        while task.status in ("queued", "running"):
            await asyncio.sleep(0.25)
            task = app.get(task_id, principal_scope=scope)
        if not task.record_id:
            raise ToolExecutionError(
                f"Image task failed ({task.error_type or 'ImageTaskError'}): "
                f"{task.error_message or 'Image task did not produce a saved result'}"
            )
        record = ImageApplication(self._runtime).get_record(
            task.record_id, principal_scope=scope
        )
        return {
            "type": "image_generation",
            "task_id": task_id,
            "record_id": task.record_id,
            "status": task.status,
            "provider_id": record.provider_id,
            "model_id": record.request.model_id,
            "message": "Images are saved and displayed in the tool card. Use the returned record_id and image_index in references to modify them. Do not regenerate this request to view its result.",
            "images": [
                {
                    "record_id": record.record_id,
                    "image_index": index,
                    "mime_type": image.mime_type,
                }
                for index, image in enumerate(record.response.images)
            ],
        }

    async def _select_model(
        self, provider_id: str | None, model_id: str | None
    ) -> tuple[str, str]:
        if provider_id and model_id:
            return provider_id, model_id
        providers = await self._runtime.providers.list_infos()
        enabled = [
            provider
            for provider in providers
            if provider.is_enabled
            and provider.type is ProviderType.OPENAI
            and (provider_id is None or provider.provider_id == provider_id)
        ]
        candidates = [
            (provider.provider_id, model.model_id)
            for provider in enabled
            for model in provider.model.values()
            if ProviderModelCapability.IMAGE_GENERATION in model.capabilities
            and (model_id is None or model.model_id == model_id)
        ]
        if candidates:
            return candidates[0]
        if model_id and len(enabled) == 1:
            return enabled[0].provider_id, model_id
        raise ToolInputError(
            "No configured image model was found. Specify provider_id and model_id, or declare an image_generation model in provider settings."
        )
