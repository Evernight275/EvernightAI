from urllib.parse import quote

from typing import Annotated

from fastapi import APIRouter, Query, Request, Response, status

from EvernightAI.core.domain.image_attachment import MAX_UPLOAD_BYTES
from EvernightAI.core.error.base import ValidationError
from EvernightAI.core.schema.file import FileArtifactInfo
from EvernightAI.interface.http.dependencies import InterfaceDependency


router = APIRouter(prefix="/files", tags=["files"])


@router.post(
    "/upload",
    response_model=FileArtifactInfo,
    status_code=status.HTTP_201_CREATED,
    operation_id="upload_image_file",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                mime_type: {"schema": {"type": "string", "format": "binary"}}
                for mime_type in ("image/png", "image/jpeg", "image/webp")
            },
        }
    },
)
async def upload_file(
    request: Request,
    interface: InterfaceDependency,
    filename: Annotated[str, Query(min_length=1, max_length=512)],
) -> FileArtifactInfo:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            parsed_length = int(content_length)
            if parsed_length < 0 or parsed_length > MAX_UPLOAD_BYTES:
                raise ValidationError("图片大小不能超过 20 MiB")
        except ValueError as exc:
            raise ValidationError("Content-Length 无效") from exc

    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_UPLOAD_BYTES:
            raise ValidationError("图片大小不能超过 20 MiB")
        body.extend(chunk)
    return interface.files.upload_file(filename, bytes(body))


@router.get(
    "/{artifact_id}", response_model=FileArtifactInfo, operation_id="get_file_artifact"
)
def get_file(
    artifact_id: str, interface: InterfaceDependency, response: Response
) -> FileArtifactInfo:
    response.headers["Cache-Control"] = "private, no-store"
    return interface.files.get_file(artifact_id)


@router.get(
    "/{artifact_id}/content", operation_id="read_file_artifact", response_class=Response
)
def read_file(
    artifact_id: str, interface: InterfaceDependency, download: bool = False
) -> Response:
    info, content = interface.files.read_file(artifact_id)
    inline = info.preview_kind == "image" and not download
    return Response(
        content,
        media_type=info.mime_type if inline else "application/octet-stream",
        headers={
            "Content-Disposition": f"{'inline' if inline else 'attachment'}; filename=\"download\"; filename*=UTF-8''{quote(info.name, safe='')}",
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox; default-src 'none'",
        },
    )
