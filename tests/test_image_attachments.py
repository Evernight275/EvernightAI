import base64
import struct
import zlib
from types import SimpleNamespace
from typing import cast

import pytest
from pydantic import ValidationError as SchemaValidationError

from EvernightAI.application.image_attachments import (
    create_image_artifact,
    resolve_image_references,
)
from EvernightAI.core.domain.file import FileArtifactStore
from EvernightAI.core.error.base import NotFoundError, ValidationError
from EvernightAI.core.error.chat import ChatInputError
from EvernightAI.core.protocol.runtime import RuntimeProtocol
from EvernightAI.core.schema.auth import PrincipalScope
from EvernightAI.core.schema.content import (
    ChatRequest,
    Content,
    ContentPart,
    ContentPartType,
    MessageRole,
)
from EvernightAI.infra.adapters.providers.anthropic.mapper import to_anthropic_request
from EvernightAI.infra.adapters.providers.gemini.mapper import to_gemini_request
from EvernightAI.infra.adapters.providers.openai_compatible.mapper import (
    to_openai_messages,
)
from EvernightAI.infra.adapters.providers.openai_responses.mapper import (
    to_openai_response_input,
)


def _png() -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    pixels = zlib.compress(b"\x00\x00\x00\x00")
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", pixels)
        + chunk(b"IEND", b"")
    )


def _jpeg() -> bytes:
    return base64.b64decode(
        "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////"
        "2wBDAf//////////////////////////////////////////////////////////////////////////////////////wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAb/"
        "xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIQAxAAAAF6AP/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAT8Af//"
        "EABQRAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQIBAT8Af//EABQRAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQMBAT8Af//Z"
    )


def _webp() -> bytes:
    return base64.b64decode("UklGRiIAAABXRUJQVlA4IBYAAAAwAQCdASoBAAEADsD+JaQAA3AAAAAA")


def _runtime() -> tuple[RuntimeProtocol, FileArtifactStore]:
    store = FileArtifactStore()
    return cast(RuntimeProtocol, SimpleNamespace(file_artifacts=store)), store


@pytest.mark.parametrize(
    ("name", "data", "mime"),
    [
        ("one.png", _png(), "image/png"),
        ("one.jpg", _jpeg(), "image/jpeg"),
        ("one.webp", _webp(), "image/webp"),
    ],
)
def test_upload_records_sniffed_bitmap_mime_and_clean_name(
    name: str, data: bytes, mime: str
) -> None:
    runtime, store = _runtime()

    info = create_image_artifact(
        runtime,
        f"../folder\\{name}\n",
        data,
        principal_scope=PrincipalScope(owner_id="alice"),
    )

    assert info.name == name
    assert info.mime_type == mime
    assert info.preview_kind == "image"
    artifact = store.get(info.artifact_id)
    assert artifact.owner_id == "alice"
    assert store.read(info.artifact_id) == data


@pytest.mark.parametrize(
    "data",
    [
        b"\x89PNG\r\n\x1a\n",
        b"\xff\xd8\xff\xd9",
        b"RIFF\x10\x00\x00\x00WEBP",
        b"not an image",
    ],
)
def test_upload_rejects_signature_only_or_invalid_bitmaps(data: bytes) -> None:
    runtime, _ = _runtime()

    with pytest.raises(ValidationError):
        create_image_artifact(runtime, "image.png", data)


def test_upload_rejects_file_over_20_mib_before_format_parsing() -> None:
    runtime, _ = _runtime()

    with pytest.raises(ValidationError, match="20 MiB"):
        create_image_artifact(runtime, "large.png", b"x" * (20 * 1024 * 1024 + 1))


@pytest.mark.asyncio
async def test_image_references_resolve_for_owner_without_mutating_request() -> None:
    runtime, store = _runtime()
    info = create_image_artifact(
        runtime,
        "image.png",
        _png(),
        principal_scope=PrincipalScope(owner_id="alice"),
    )
    request = ChatRequest(
        model_id="model",
        messages=[
            Content(
                role=MessageRole.USER,
                content=[
                    ContentPart(
                        type=ContentPartType.IMAGE,
                        artifact_id=info.artifact_id,
                    )
                ],
            )
        ],
    )
    original = request.model_copy(deep=True)

    resolved = await resolve_image_references(
        runtime, request, principal_scope=PrincipalScope(owner_id="alice")
    )

    assert request == original
    resolved_content = resolved.messages[0].content
    assert resolved_content is not None
    part = resolved_content[0]
    assert part.artifact_id is None
    assert part.data is not None and part.data.startswith("data:image/png;base64,")
    with pytest.raises(NotFoundError):
        store.get(info.artifact_id, principal_scope=PrincipalScope(owner_id="bob"))
    with pytest.raises(ChatInputError, match="无权访问"):
        await resolve_image_references(
            runtime, request, principal_scope=PrincipalScope(owner_id="bob")
        )


@pytest.mark.asyncio
async def test_resolved_image_maps_through_all_four_provider_formats() -> None:
    runtime, _ = _runtime()
    info = create_image_artifact(runtime, "image.png", _png())
    request = ChatRequest(
        model_id="model",
        messages=[
            Content(
                role=MessageRole.USER,
                content=[
                    ContentPart(type=ContentPartType.IMAGE, artifact_id=info.artifact_id)
                ],
            )
        ],
    )

    resolved = await resolve_image_references(runtime, request)
    mappings = [
        to_openai_messages(resolved.messages),
        to_openai_response_input(resolved.messages),
        to_gemini_request(resolved.messages),
        to_anthropic_request(resolved.messages, "model"),
    ]

    encoded = base64.b64encode(_png()).decode("ascii")
    assert all(encoded in repr(mapping) for mapping in mappings)


def test_image_reference_cannot_be_combined_with_inline_source() -> None:
    with pytest.raises(SchemaValidationError, match="cannot be combined"):
        ContentPart(
            type=ContentPartType.IMAGE,
            artifact_id="artifact",
            url="https://example.test/image.png",
        )
