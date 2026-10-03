import asyncio
import base64
from collections.abc import Awaitable, Callable
from ipaddress import ip_address, ip_network
import logging
import socket
from time import monotonic

import httpx

from EvernightAI.core.protocol.image import ImageArchiveProtocol
from EvernightAI.core.schema.image import GeneratedImage, ImageGenerationResponse
from EvernightAI.infra.adapters.images.bitmap import bitmap_mime


LOGGER = logging.getLogger("EvernightAI.images")
FAKE_IP_NETWORKS = (ip_network("198.18.0.0/15"), ip_network("2001:2::/48"))


async def resolve_addresses(host: str, port: int) -> list[str]:
    try:
        address = ip_address(host)
    except ValueError:
        pass
    else:
        return [str(address)]
    answers = await asyncio.get_running_loop().getaddrinfo(
        host, port, type=socket.SOCK_STREAM
    )
    addresses = list(dict.fromkeys(str(answer[4][0]) for answer in answers))
    # Proxy DNS may synthesize benchmark addresses instead of the remote IPs.
    if addresses and all(
        any(ip_address(address) in network for network in FAKE_IP_NETWORKS)
        for address in addresses
    ):
        return await _resolve_public_addresses(host)
    return addresses


async def _resolve_public_addresses(
    host: str, *, transport: httpx.AsyncBaseTransport | None = None
) -> list[str]:
    addresses: list[str] = []
    async with httpx.AsyncClient(
        transport=transport, trust_env=False, follow_redirects=False, timeout=10
    ) as client:
        for record_type in (1, 28):
            response = await client.get(
                "https://1.1.1.1/dns-query",
                params={"name": host, "type": str(record_type)},
                headers={"Accept": "application/dns-json"},
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("Status") != 0:
                raise ValueError("Image DNS lookup failed")
            for answer in payload.get("Answer", []):
                if answer.get("type") == record_type:
                    address = ip_address(answer["data"])
                    if address.version != (4 if record_type == 1 else 6):
                        raise ValueError("Invalid image DNS address")
                    addresses.append(str(address))
    return list(dict.fromkeys(addresses))


class PublicImageArchive(ImageArchiveProtocol):
    def __init__(
        self,
        *,
        resolver: Callable[[str, int], Awaitable[list[str]]] = resolve_addresses,
        transport: httpx.AsyncBaseTransport | None = None,
        max_bytes: int = 20_000_000,
        total_bytes: int = 50_000_000,
        timeout_seconds: float = 30,
    ) -> None:
        self._resolver = resolver
        self._transport = transport
        self._max_bytes = max_bytes
        self._total_bytes = total_bytes
        self._timeout = timeout_seconds

    async def archive(
        self, response: ImageGenerationResponse
    ) -> ImageGenerationResponse:
        images: list[GeneratedImage] = []
        remaining = self._total_bytes
        deadline = monotonic() + self._timeout
        for image in response.images:
            if image.base64_data is not None:
                images.append(image)
                continue
            try:
                async with asyncio.timeout(max(0, deadline - monotonic())):
                    content = await self._download(
                        str(image.url), min(self._max_bytes, remaining)
                    )
                mime = bitmap_mime(content)
            except Exception as exc:
                LOGGER.warning("Image archive download failed (%s)", type(exc).__name__)
                images.append(image)
            else:
                remaining -= len(content)
                images.append(
                    image.model_copy(
                        update={
                            "base64_data": base64.b64encode(content).decode("ascii"),
                            "mime_type": mime,
                        }
                    )
                )
        return response.model_copy(
            update={
                "images": images,
                "persistence_warning": "archive_incomplete"
                if any(not image.base64_data for image in images)
                else None,
            }
        )

    async def _download(self, source: str, max_bytes: int) -> bytes:
        url = httpx.URL(source)
        # Revalidate TLS on every redirect, even when different hosts share an IP.
        async with httpx.AsyncClient(
            transport=self._transport,
            trust_env=False,
            follow_redirects=False,
            timeout=10,
            limits=httpx.Limits(max_keepalive_connections=0),
        ) as client:
            for _ in range(4):
                if (
                    url.scheme not in {"http", "https"}
                    or url.username
                    or url.password
                    or url.port not in {None, 80, 443}
                ):
                    raise ValueError("Unsupported image URL")
                addresses = await self._resolver(
                    url.host, url.port or (443 if url.scheme == "https" else 80)
                )
                if not addresses or any(
                    not ip_address(address).is_global
                    or ip_address(address).is_multicast
                    for address in addresses
                ):
                    raise ValueError("Image URLs must resolve only to public addresses")
                # Pin the connection to a validated address while preserving Host and TLS identity.
                target = url.copy_with(host=addresses[0])
                client.cookies.clear()
                async with client.stream(
                    "GET",
                    target,
                    headers={"Host": url.netloc.decode("ascii")},
                    extensions={"sni_hostname": url.raw_host.decode("ascii")},
                ) as result:
                    if result.is_redirect:
                        next_url = url.join(result.headers["location"])
                        if url.scheme == "https" and next_url.scheme != "https":
                            raise ValueError("Image redirects cannot downgrade HTTPS")
                        url = next_url
                        continue
                    result.raise_for_status()
                    content = bytearray()
                    async for chunk in result.aiter_bytes():
                        content.extend(chunk)
                        if len(content) > max_bytes:
                            raise ValueError("Image archive size limit exceeded")
                    return bytes(content)
        raise ValueError("Image redirect limit exceeded")
