"""Application services for file backed chat image attachments."""

import base64

from EvernightAI.core.domain.image_attachment import (
    MAX_REQUEST_IMAGE_BYTES,
    MAX_REQUEST_IMAGES,
    MAX_UPLOAD_BYTES,
    bitmap_mime,
    clean_image_filename,
)
from EvernightAI.core.error.base import NotFoundError, ValidationError
from EvernightAI.core.error.chat import ChatInputError
from EvernightAI.core.protocol.runtime import RuntimeProtocol
from EvernightAI.core.schema.auth import PrincipalScope
from EvernightAI.core.schema.content import ChatRequest, ContentPartType
from EvernightAI.core.schema.file import FileArtifact, FileArtifactInfo


def create_image_artifact(
    runtime: RuntimeProtocol,
    filename: str,
    content: bytes,
    *,
    principal_scope: PrincipalScope | None = None,
) -> FileArtifactInfo:
    if not content or len(content) > MAX_UPLOAD_BYTES:
        raise ValidationError("图片大小必须大于 0 且不超过 20 MiB")
    mime_type = bitmap_mime(content)
    artifact = FileArtifact(
        owner_id=principal_scope.owner_id if principal_scope is not None else None,
        name=clean_image_filename(filename),
        mime_type=mime_type,
        preview_kind="image",
        size_bytes=len(content),
    )
    runtime.file_artifacts.save(artifact, content)
    return artifact.info()


async def resolve_image_references(
    runtime: RuntimeProtocol,
    request: ChatRequest,
    *,
    principal_scope: PrincipalScope | None = None,
) -> ChatRequest:
    resolved = request.model_copy(deep=True)
    referenced = [
        part
        for message in resolved.messages
        for part in message.content or []
        if part.type is ContentPartType.IMAGE and part.artifact_id is not None
    ]
    if len(referenced) > MAX_REQUEST_IMAGES:
        raise ChatInputError("每个请求最多引用 10 张图片")

    total_bytes = 0
    for part in referenced:
        artifact_id = part.artifact_id
        if artifact_id is None:
            raise ChatInputError("图片附件引用无效")
        try:
            artifact = runtime.file_artifacts.get(
                artifact_id, principal_scope=principal_scope
            )
        except NotFoundError as exc:
            raise ChatInputError("图片附件不存在或无权访问") from exc
        if artifact.preview_kind != "image" or artifact.mime_type not in {
            "image/png",
            "image/jpeg",
            "image/webp",
        }:
            raise ChatInputError("引用的文件不是受支持的图片")
        total_bytes += artifact.size_bytes
        if artifact.size_bytes > MAX_UPLOAD_BYTES:
            raise ChatInputError("图片附件大小无效")
        if total_bytes > MAX_REQUEST_IMAGE_BYTES:
            raise ChatInputError("每个请求引用图片总大小不能超过 50 MiB")

        try:
            content = runtime.file_artifacts.read(
                artifact_id, principal_scope=principal_scope
            )
        except NotFoundError as exc:
            raise ChatInputError("图片附件不存在或无权访问") from exc
        if len(content) != artifact.size_bytes:
            raise ChatInputError("图片附件大小无效")
        try:
            detected_mime = bitmap_mime(content)
        except ValidationError as exc:
            raise ChatInputError("图片附件格式无效") from exc
        if detected_mime != artifact.mime_type:
            raise ChatInputError("图片附件格式与文件记录不匹配")
        part.data = f"data:{artifact.mime_type};base64,{base64.b64encode(content).decode('ascii')}"
        part.mime_type = artifact.mime_type
        part.artifact_id = None
    return resolved
