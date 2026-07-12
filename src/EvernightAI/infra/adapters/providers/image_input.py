import base64
import binascii
import re

from EvernightAI.core.error.chat import ChatInputError
from EvernightAI.core.schema.content import ContentPart


_DATA_URI_PATTERN = re.compile(
    r"^data:(?P<mime_type>image/[a-zA-Z0-9.+-]+);base64,(?P<data>.+)$",
    re.DOTALL,
)


def image_url(part: ContentPart) -> str:
    validate_image_source(part)
    if part.url:
        return part.url

    mime_type, data = inline_image(part)
    return f"data:{mime_type};base64,{data}"


def inline_image(part: ContentPart) -> tuple[str, str]:
    if not part.data:
        raise ChatInputError("Image content part requires data")

    match = _DATA_URI_PATTERN.fullmatch(part.data)
    if match is not None:
        mime_type = match.group("mime_type")
        if part.mime_type and part.mime_type != mime_type:
            raise ChatInputError("Image data URI mime type does not match mime_type")
        data = match.group("data")
        _validate_base64(data)
        return mime_type, data

    if not part.mime_type:
        raise ChatInputError("Base64 image content part requires mime_type")
    if not part.mime_type.startswith("image/"):
        raise ChatInputError("Image content part mime_type must start with image/")

    _validate_base64(part.data)
    return part.mime_type, part.data


def validate_image_source(part: ContentPart) -> None:
    if part.url and part.data:
        raise ChatInputError("Image content part must use either url or data, not both")
    if not part.url and not part.data:
        raise ChatInputError("Image content part requires url or data")


def _validate_base64(data: str) -> None:
    try:
        base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ChatInputError("Image content part data must be valid base64") from exc
