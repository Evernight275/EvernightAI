import base64
import struct
import zlib

import pytest
from pydantic import ValidationError

from EvernightAI.core.schema.image import (
    ImageEditInput,
    ImageEditRequest,
    ImageMaskInput,
)
from EvernightAI.infra.adapters.providers.openai_compatible.images import (
    image_edit_params,
)


def png(width: int = 2, height: int = 2, alpha: bool = True) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack("!I", len(data))
            + kind
            + data
            + struct.pack("!I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    pixel = b"\x00\x00\x00\x00" if alpha else b"\x00\x00\x00"
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(
            b"IHDR",
            struct.pack("!IIBBBBB", width, height, 8, 6 if alpha else 2, 0, 0, 0),
        )
        + chunk(b"IDAT", zlib.compress((b"\x00" + pixel * width) * height))
        + chunk(b"IEND", b"")
    )


def input_image(data: bytes) -> ImageEditInput:
    return ImageEditInput(
        base64_data=base64.b64encode(data).decode(), mime_type="image/png"
    )


def test_mask_matches_first_image_and_is_uploaded_as_real_png_file() -> None:
    original, mask_data = png(alpha=False), png()
    request = ImageEditRequest(
        model_id="image-model",
        prompt="Replace region",
        images=[input_image(original), input_image(png(3, 4))],
        mask=ImageMaskInput(base64_data=base64.b64encode(mask_data).decode()),
    )
    params = image_edit_params(request)
    assert params["mask"] == ("mask.png", mask_data, "image/png")
    assert params["image"][0] == ("reference-1.png", original, "image/png")
    assert "mask" not in image_edit_params(request.model_copy(update={"mask": None}))


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (png(alpha=False), "alpha channel"),
        (b"\x89PNG\r\n\x1a\nwrong", "valid PNG"),
        (png(0, 2), "dimensions"),
    ],
)
def test_invalid_masks_fail_before_provider_dispatch(data: bytes, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        ImageMaskInput(base64_data=base64.b64encode(data).decode())


def test_mask_size_mismatch_and_jpeg_first_input_are_rejected() -> None:
    mask = ImageMaskInput(base64_data=base64.b64encode(png()).decode())
    with pytest.raises(ValidationError, match="match the first image"):
        ImageEditRequest(
            model_id="image", prompt="Edit", images=[input_image(png(3, 4))], mask=mask
        )
    jpeg = ImageEditInput(
        base64_data=base64.b64encode(b"\xff\xd8\xffjpeg").decode(),
        mime_type="image/jpeg",
    )
    with pytest.raises(ValidationError, match="must be PNG"):
        ImageEditRequest(model_id="image", prompt="Edit", images=[jpeg], mask=mask)


@pytest.mark.asyncio
async def test_sdk_sends_mask_and_ordered_references_without_model_discovery() -> None:
    import httpx
    from email.parser import BytesParser
    from email.policy import default
    from openai import AsyncOpenAI

    from EvernightAI.core.schema.provider import ProviderConfig, ProviderType
    from EvernightAI.infra.adapters.providers.openai_compatible.instance import (
        OpenAICompatibleProviderInstance,
    )

    calls: list[httpx.Request] = []
    original, mask = png(alpha=False), png()

    def respond(call: httpx.Request) -> httpx.Response:
        calls.append(call)
        return httpx.Response(
            200, json={"data": [{"b64_json": base64.b64encode(original).decode()}]}
        )

    instance = OpenAICompatibleProviderInstance(
        ProviderConfig(provider_id="main", name="Main", type=ProviderType.OPENAI)
    )
    await instance._client.close()
    instance._client = AsyncOpenAI(
        api_key="test",
        base_url="https://provider.example/v1",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )
    try:
        await instance.edit_images(
            ImageEditRequest(
                model_id="undeclared-image",
                prompt="Edit area",
                images=[input_image(original), input_image(original)],
                mask=ImageMaskInput(base64_data=base64.b64encode(mask).decode()),
            )
        )
        assert len(calls) == 1
        call = calls[0]
        assert call.url.path == "/v1/images/edits"
        message = BytesParser(policy=default).parsebytes(
            f"Content-Type: {call.headers['content-type']}\r\n\r\n".encode()
            + call.content
        )
        files = [part for part in message.iter_parts() if part.get_filename()]
        assert [
            part.get_param("name", header="content-disposition") for part in files
        ] == ["image[]", "image[]", "mask"]
        assert [part.get_payload(decode=True) for part in files] == [
            original,
            original,
            mask,
        ]
        assert all(part.get_content_type() == "image/png" for part in files)
    finally:
        await instance.close()
