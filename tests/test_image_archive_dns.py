import asyncio
import base64
import socket
from typing import Any

import httpx
import pytest

from EvernightAI.infra.adapters.images import archive
from tests.test_image_generation import PNG
from tests.test_image_history import url_response


def system_addresses(monkeypatch: pytest.MonkeyPatch, addresses: list[str]) -> None:
    async def resolve(*_args: Any, **_kwargs: Any) -> list[Any]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in addresses
        ]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "addresses",
    [["198.18.1.157"], ["2001:2::67"], ["198.18.1.157", "2001:2::67"]],
)
async def test_fake_ip_dns_archives_through_verified_public_addresses(
    monkeypatch: pytest.MonkeyPatch, addresses: list[str]
) -> None:
    system_addresses(monkeypatch, addresses)
    resolve_public = archive._resolve_public_addresses

    def dns_response(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "1.1.1.1"
        assert request.url.params["name"] == "images.example"
        assert request.headers["accept"] == "application/dns-json"
        assert "authorization" not in request.headers
        kind = int(request.url.params["type"])
        return httpx.Response(
            200,
            json={
                "Status": 0,
                "Answer": [{"type": kind, "data": "93.184.216.34"}]
                if kind == 1
                else [],
            },
        )

    async def public_addresses(host: str) -> list[str]:
        return await resolve_public(host, transport=httpx.MockTransport(dns_response))

    monkeypatch.setattr(archive, "_resolve_public_addresses", public_addresses)

    def image_response(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "93.184.216.34"
        assert request.headers["host"] == "images.example"
        assert request.extensions["sni_hostname"] == "images.example"
        return httpx.Response(200, content=base64.b64decode(PNG))

    response = await archive.PublicImageArchive(
        transport=httpx.MockTransport(image_response)
    ).archive(url_response())
    assert response.images[0].base64_data == PNG
    assert response.persistence_warning is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "addresses",
    [[], ["93.184.216.34"], ["10.0.0.1"], ["198.18.1.1", "10.0.0.1"]],
)
async def test_other_dns_results_do_not_use_public_dns(
    monkeypatch: pytest.MonkeyPatch, addresses: list[str]
) -> None:
    system_addresses(monkeypatch, addresses)

    async def unexpected_lookup(_host: str) -> list[str]:
        pytest.fail("Only exclusively Fake-IP DNS results should trigger a fallback")

    monkeypatch.setattr(archive, "_resolve_public_addresses", unexpected_lookup)
    assert await archive.resolve_addresses("images.example", 443) == addresses


@pytest.mark.asyncio
@pytest.mark.parametrize("host", ["198.18.1.1", "2001:2::1", "127.0.0.1", "::1"])
async def test_literal_addresses_never_trigger_dns(
    monkeypatch: pytest.MonkeyPatch, host: str
) -> None:
    async def unexpected_lookup(*_args: Any, **_kwargs: Any) -> list[Any]:
        pytest.fail(
            "Literal addresses must retain their original safety classification"
        )

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", unexpected_lookup)
    assert await archive.resolve_addresses(host, 443) == [host]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "addresses", [[], ["127.0.0.1"], ["93.184.216.34", "10.0.0.1"]]
)
async def test_public_dns_fallback_cannot_bypass_image_address_validation(
    monkeypatch: pytest.MonkeyPatch, addresses: list[str]
) -> None:
    system_addresses(monkeypatch, ["198.18.1.157"])

    async def public_addresses(_host: str) -> list[str]:
        return addresses

    monkeypatch.setattr(archive, "_resolve_public_addresses", public_addresses)

    def unexpected_download(_request: httpx.Request) -> httpx.Response:
        pytest.fail("Unsafe fallback addresses must never be requested")

    response = await archive.PublicImageArchive(
        transport=httpx.MockTransport(unexpected_download)
    ).archive(url_response())
    assert response.persistence_warning == "archive_incomplete"
    assert response.images[0].base64_data is None


@pytest.mark.asyncio
async def test_public_dns_collects_ipv4_and_ipv6_and_ignores_cname() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        kind = int(request.url.params["type"])
        return httpx.Response(
            200,
            json={
                "Status": 0,
                "Answer": [
                    {"type": 5, "data": "cdn.example"},
                    {
                        "type": kind,
                        "data": "93.184.216.34" if kind == 1 else "2606:4700::1111",
                    },
                ],
            },
        )

    assert await archive._resolve_public_addresses(
        "images.example", transport=httpx.MockTransport(respond)
    ) == ["93.184.216.34", "2606:4700::1111"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode", ["unavailable", "dns_failure", "invalid_address", "wrong_family"]
)
async def test_failed_public_dns_retains_image_url_and_warning(
    monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    system_addresses(monkeypatch, ["198.18.1.157"])
    resolve_public = archive._resolve_public_addresses

    def respond(_request: httpx.Request) -> httpx.Response:
        if mode == "unavailable":
            return httpx.Response(503)
        return httpx.Response(
            200,
            json={
                "Status": 3 if mode == "dns_failure" else 0,
                "Answer": [
                    {
                        "type": 1,
                        "data": "invalid" if mode == "invalid_address" else "::1",
                    }
                ],
            },
        )

    async def public_addresses(host: str) -> list[str]:
        return await resolve_public(host, transport=httpx.MockTransport(respond))

    monkeypatch.setattr(archive, "_resolve_public_addresses", public_addresses)

    def unexpected_download(_request: httpx.Request) -> httpx.Response:
        pytest.fail("Failed DNS lookups must not reach the image transport")

    original = url_response()
    response = await archive.PublicImageArchive(
        transport=httpx.MockTransport(unexpected_download)
    ).archive(original)
    assert response.images[0].url == original.images[0].url
    assert response.persistence_warning == "archive_incomplete"
