"""Validation and limits for user supplied bitmap image attachments."""

import unicodedata
import zlib

from EvernightAI.core.error.base import ValidationError


MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_REQUEST_IMAGE_BYTES = 50 * 1024 * 1024
MAX_REQUEST_IMAGES = 10


def bitmap_mime(data: bytes) -> str:
    if _valid_png(data):
        return "image/png"
    if _valid_jpeg(data):
        return "image/jpeg"
    if _valid_webp(data):
        return "image/webp"
    raise ValidationError("仅支持有效的 PNG、JPEG 或 WebP 图片")


def clean_image_filename(filename: str) -> str:
    name = filename.replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(char for char in name if unicodedata.category(char) != "Cc")
    name = name.strip().strip(".")[:200]
    if not name:
        raise ValidationError("图片文件名无效")
    return name


def _valid_png(data: bytes) -> bool:
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return False
    offset = 8
    saw_header = saw_data = saw_end = False
    while offset + 12 <= len(data):
        length = int.from_bytes(data[offset : offset + 4], "big")
        kind = data[offset + 4 : offset + 8]
        end = offset + 12 + length
        if end > len(data):
            return False
        payload = data[offset + 8 : offset + 8 + length]
        expected_crc = int.from_bytes(data[offset + 8 + length : end], "big")
        if zlib.crc32(kind + payload) & 0xFFFFFFFF != expected_crc:
            return False
        if not saw_header:
            if kind != b"IHDR" or length != 13:
                return False
            width = int.from_bytes(payload[:4], "big")
            height = int.from_bytes(payload[4:8], "big")
            if width == 0 or height == 0:
                return False
            saw_header = True
        elif kind == b"IDAT":
            saw_data = True
        elif kind == b"IEND":
            if length != 0 or not saw_data or end != len(data):
                return False
            saw_end = True
            break
        offset = end
    return saw_header and saw_data and saw_end


def _valid_jpeg(data: bytes) -> bool:
    if (
        len(data) < 12
        or not data.startswith(b"\xff\xd8")
        or not data.endswith(b"\xff\xd9")
    ):
        return False
    offset = 2
    saw_frame = saw_scan = False
    while offset < len(data) - 2:
        if data[offset] != 0xFF:
            return False
        while offset < len(data) and data[offset] == 0xFF:
            offset += 1
        if offset >= len(data):
            return False
        marker = data[offset]
        offset += 1
        if marker == 0xD9:
            return saw_frame and saw_scan and offset == len(data)
        if marker in {0xD8, 0x01} or 0xD0 <= marker <= 0xD7:
            continue
        if offset + 2 > len(data):
            return False
        length = int.from_bytes(data[offset : offset + 2], "big")
        if length < 2 or offset + length > len(data):
            return False
        if marker in {
            0xC0,
            0xC1,
            0xC2,
            0xC3,
            0xC5,
            0xC6,
            0xC7,
            0xC9,
            0xCA,
            0xCB,
            0xCD,
            0xCE,
            0xCF,
        }:
            saw_frame = length >= 8
        if marker == 0xDA:
            saw_scan = True
            end = data.find(b"\xff\xd9", offset + length)
            return saw_frame and end == len(data) - 2
        offset += length
    return False


def _valid_webp(data: bytes) -> bool:
    if len(data) < 20 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return False
    if int.from_bytes(data[4:8], "little") != len(data) - 8:
        return False
    offset = 12
    saw_image_chunk = False
    while offset + 8 <= len(data):
        kind = data[offset : offset + 4]
        size = int.from_bytes(data[offset + 4 : offset + 8], "little")
        end = offset + 8 + size + (size & 1)
        if end > len(data):
            return False
        payload = data[offset + 8 : offset + 8 + size]
        if kind == b"VP8 " and size >= 10 and payload[3:6] == b"\x9d\x01\x2a":
            saw_image_chunk = True
        if kind == b"VP8L" and size >= 5 and payload[0] == 0x2F:
            saw_image_chunk = True
        if kind == b"ANMF" and size >= 24:
            frame_kind = payload[16:20]
            frame_size = int.from_bytes(payload[20:24], "little")
            if (
                frame_kind in {b"VP8 ", b"VP8L"}
                and 24 + frame_size + (frame_size & 1) <= size
            ):
                saw_image_chunk = True
        offset = end
    return saw_image_chunk and offset == len(data)
