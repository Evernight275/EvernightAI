from fastapi import APIRouter, Query, Response

from EvernightAI.core.schema.image import (
    ImageGenerationRecord,
    ImageGenerationResponse,
    ImageHistoryPage,
)
from EvernightAI.interface.http.dependencies import InterfaceDependency
from EvernightAI.interface.http.schema import DirectImageGenerationRequest


router = APIRouter(prefix="/images", tags=["images"])


@router.post(
    "/generations",
    response_model=ImageGenerationResponse,
    response_model_exclude_none=True,
    summary="Generate images from a text prompt",
    operation_id="generate_images",
)
async def generate_images(
    request: DirectImageGenerationRequest,
    interface: InterfaceDependency,
    response: Response,
) -> ImageGenerationResponse:
    response.headers["Cache-Control"] = "no-store"
    return await interface.providers.generate_images(
        request.provider_id, request.request
    )


@router.get(
    "/records",
    response_model=ImageHistoryPage,
    response_model_exclude_none=True,
    summary="List image generation history",
    operation_id="list_image_records",
)
async def list_image_records(
    interface: InterfaceDependency,
    response: Response,
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=512),
) -> ImageHistoryPage:
    response.headers["Cache-Control"] = "no-store"
    return interface.providers.list_image_records(limit=limit, cursor=cursor)


@router.get(
    "/records/{record_id}",
    response_model=ImageGenerationRecord,
    response_model_exclude_none=True,
    summary="Get a saved image generation",
    operation_id="get_image_record",
)
async def get_image_record(
    record_id: str, interface: InterfaceDependency, response: Response
) -> ImageGenerationRecord:
    response.headers["Cache-Control"] = "no-store"
    return interface.providers.get_image_record(record_id)


@router.delete(
    "/records/{record_id}",
    status_code=204,
    summary="Delete saved images",
    operation_id="delete_image_record",
)
async def delete_image_record(
    record_id: str, interface: InterfaceDependency
) -> Response:
    interface.providers.delete_image_record(record_id)
    return Response(status_code=204, headers={"Cache-Control": "no-store"})
