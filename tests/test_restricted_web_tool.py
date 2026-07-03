from collections.abc import Callable

import httpx
import pytest

from EvernightAI.core.domain.tool import ToolManager, ToolRegister
from EvernightAI.core.error.tool import (
    ToolExecutionError,
    ToolInputError,
    ToolPolicyError,
)
from EvernightAI.core.schema.tool import ToolCall
from EvernightAI.infra.registrations.tool.restricted_web import (
    register_restricted_web_tools,
)


@pytest.mark.asyncio
async def test_restricted_web_request_requires_approval(tmp_path) -> None:
    register = ToolRegister()
    register_restricted_web_tools(
        register,
        allowed_hosts={"example.test"},
        download_directory=tmp_path,
    )
    manager = ToolManager(register)

    with pytest.raises(ToolPolicyError) as exc_info:
        await manager.execute(
            ToolCall(
                tool_call_id="call-1",
                tool_call={
                    "name": "http_request",
                    "arguments": {"url": "https://example.test"},
                },
            )
        )

    assert exc_info.value.detail == "Tool call requires approval"


@pytest.mark.asyncio
async def test_http_request_sends_post_and_truncates_response(monkeypatch) -> None:
    client = FakeAsyncClient(
        request_response=httpx.Response(
            201,
            text="abcdef",
            headers={"x-test": "yes"},
        )
    )
    monkeypatch.setattr(
        "EvernightAI.infra.adapters.tool.restricted_web.httpx.AsyncClient",
        fake_client_factory(client),
    )
    register = ToolRegister()
    register_restricted_web_tools(
        register,
        allowed_hosts={"example.test"},
        timeout_seconds=2.5,
        max_response_chars=3,
    )
    manager = ToolManager(register)

    result = await manager.execute(
        ToolCall(
            tool_call_id="call-1",
            tool_call={
                "name": "http_request",
                "arguments": {
                    "url": "https://example.test/api",
                    "method": "post",
                    "headers": {"x-client": "test"},
                    "json": {"ok": True},
                },
            },
            metadata={"approved": True},
        )
    )

    assert client.timeout == 2.5
    assert client.request_calls == [
        {
            "method": "POST",
            "url": "https://example.test/api",
            "headers": {"x-client": "test"},
            "content": None,
            "json": {"ok": True},
        }
    ]
    assert result.tool_call_result["status_code"] == 201
    assert result.tool_call_result["headers"]["x-test"] == "yes"
    assert result.tool_call_result["text"] == "abc"
    assert result.tool_call_result["truncated"] is True


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (
            {"url": "https://blocked.test"},
            "not allowed",
        ),
        (
            {"url": "https://example.test", "method": "PUT"},
            "Only GET and POST",
        ),
        (
            {"url": "https://example.test", "headers": {"x-test": 1}},
            "must be strings",
        ),
        (
            {"url": "https://example.test", "method": "GET", "body": "data"},
            "GET requests cannot include",
        ),
    ],
)
@pytest.mark.asyncio
async def test_http_request_rejects_invalid_input(
    arguments: dict[str, object],
    message: str,
) -> None:
    register = ToolRegister()
    register_restricted_web_tools(register, allowed_hosts={"example.test"})
    manager = ToolManager(register)

    with pytest.raises(ToolExecutionError) as exc_info:
        await manager.execute(
            ToolCall(
                tool_call_id="call-1",
                tool_call={
                    "name": "http_request",
                    "arguments": arguments,
                },
                metadata={"approved": True},
            )
        )

    assert isinstance(exc_info.value.cause, ToolInputError)
    assert message in str(exc_info.value.cause)


@pytest.mark.asyncio
async def test_scrape_web_page_extracts_visible_text(monkeypatch) -> None:
    client = FakeAsyncClient(
        get_response=httpx.Response(
            200,
            text=(
                "<html><head><title>Example Page</title>"
                "<style>.hidden{display:none}</style></head>"
                "<body><h1>Hello</h1><script>secret()</script>"
                "<p>Visible text</p><noscript>hidden fallback</noscript></body></html>"
            ),
        )
    )
    monkeypatch.setattr(
        "EvernightAI.infra.adapters.tool.restricted_web.httpx.AsyncClient",
        fake_client_factory(client),
    )
    register = ToolRegister()
    register_restricted_web_tools(register, allowed_hosts={"example.test"})
    manager = ToolManager(register)

    result = await manager.execute(
        ToolCall(
            tool_call_id="call-1",
            tool_call={
                "name": "scrape_web_page",
                "arguments": {"url": "https://example.test/page"},
            },
            metadata={"approved": True},
        )
    )

    assert client.get_calls == ["https://example.test/page"]
    assert result.tool_call_result == {
        "url": "https://example.test/page",
        "status_code": 200,
        "title": "Example Page",
        "text": "Example Page Hello Visible text",
        "truncated": False,
    }


@pytest.mark.asyncio
async def test_download_file_writes_inside_output_directory(tmp_path, monkeypatch) -> None:
    client = FakeAsyncClient(get_response=httpx.Response(200, content=b"hello"))
    monkeypatch.setattr(
        "EvernightAI.infra.adapters.tool.restricted_web.httpx.AsyncClient",
        fake_client_factory(client),
    )
    register = ToolRegister()
    register_restricted_web_tools(
        register,
        allowed_hosts={"example.test"},
        download_directory=tmp_path,
    )
    manager = ToolManager(register)

    result = await manager.execute(
        ToolCall(
            tool_call_id="call-1",
            tool_call={
                "name": "download_file",
                "arguments": {
                    "url": "https://example.test/file.txt",
                    "path": "nested/file.txt",
                },
            },
            metadata={"approved": True},
        )
    )

    assert client.get_calls == ["https://example.test/file.txt"]
    assert result.tool_call_result == {
        "url": "https://example.test/file.txt",
        "path": "nested/file.txt",
        "status_code": 200,
        "bytes_written": 5,
    }
    assert (tmp_path / "nested" / "file.txt").read_bytes() == b"hello"


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (
            {
                "url": "https://example.test/file.txt",
                "path": "../escape.txt",
            },
            "inside the output directory",
        ),
        (
            {
                "url": "https://example.test/file.txt",
                "path": "file.txt",
                "overwrite": "yes",
            },
            "overwrite value must be a boolean",
        ),
    ],
)
@pytest.mark.asyncio
async def test_download_file_rejects_invalid_output_arguments(
    tmp_path,
    arguments: dict[str, object],
    message: str,
) -> None:
    register = ToolRegister()
    register_restricted_web_tools(
        register,
        allowed_hosts={"example.test"},
        download_directory=tmp_path,
    )
    manager = ToolManager(register)

    with pytest.raises(ToolExecutionError) as exc_info:
        await manager.execute(
            ToolCall(
                tool_call_id="call-1",
                tool_call={
                    "name": "download_file",
                    "arguments": arguments,
                },
                metadata={"approved": True},
            )
        )

    assert isinstance(exc_info.value.cause, ToolInputError)
    assert message in str(exc_info.value.cause)
    assert not (tmp_path / "escape.txt").exists()


@pytest.mark.asyncio
async def test_download_file_rejects_oversized_response(tmp_path, monkeypatch) -> None:
    client = FakeAsyncClient(get_response=httpx.Response(200, content=b"abcdef"))
    monkeypatch.setattr(
        "EvernightAI.infra.adapters.tool.restricted_web.httpx.AsyncClient",
        fake_client_factory(client),
    )
    register = ToolRegister()
    register_restricted_web_tools(
        register,
        allowed_hosts={"example.test"},
        download_directory=tmp_path,
        max_download_bytes=3,
    )
    manager = ToolManager(register)

    with pytest.raises(ToolExecutionError) as exc_info:
        await manager.execute(
            ToolCall(
                tool_call_id="call-1",
                tool_call={
                    "name": "download_file",
                    "arguments": {
                        "url": "https://example.test/file.txt",
                        "path": "file.txt",
                    },
                },
                metadata={"approved": True},
            )
        )

    assert isinstance(exc_info.value.cause, ToolInputError)
    assert "exceeds max_bytes" in str(exc_info.value.cause)
    assert not (tmp_path / "file.txt").exists()


def test_register_restricted_web_tools_registers_download_only_when_configured(
    tmp_path,
) -> None:
    without_download = ToolRegister()
    register_restricted_web_tools(without_download, allowed_hosts={"example.test"})

    with_download = ToolRegister()
    register_restricted_web_tools(
        with_download,
        allowed_hosts={"example.test"},
        download_directory=tmp_path,
        timeout_seconds=1.5,
        max_response_chars=100,
        max_download_bytes=200,
    )

    assert [tool.name for tool in without_download.list_tools()] == [
        "http_request",
        "scrape_web_page",
    ]
    assert [tool.name for tool in with_download.list_tools()] == [
        "http_request",
        "scrape_web_page",
        "download_file",
    ]
    assert with_download.get("http_request").metadata == {
        "allowed_hosts": ["example.test"],
        "timeout_seconds": 1.5,
        "max_response_chars": 100,
    }
    assert with_download.get("download_file").metadata == {
        "output_directory": str(tmp_path.resolve()),
        "allowed_hosts": ["example.test"],
        "timeout_seconds": 1.5,
        "max_bytes": 200,
    }


class FakeAsyncClient:
    def __init__(
        self,
        *,
        request_response: httpx.Response | None = None,
        get_response: httpx.Response | None = None,
    ) -> None:
        self.request_response = request_response
        self.get_response = get_response
        self.timeout: float | None = None
        self.request_calls: list[dict[str, object]] = []
        self.get_calls: list[str] = []

    async def __aenter__(self) -> "FakeAsyncClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None,
        content: str | None,
        json: object,
    ) -> httpx.Response:
        self.request_calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "content": content,
                "json": json,
            }
        )
        if self.request_response is None:
            raise AssertionError("Unexpected request call")
        return self.request_response

    async def get(self, url: str) -> httpx.Response:
        self.get_calls.append(url)
        if self.get_response is None:
            raise AssertionError("Unexpected get call")
        return self.get_response


def fake_client_factory(
    client: FakeAsyncClient,
) -> Callable[..., FakeAsyncClient]:
    def factory(*, timeout: float) -> FakeAsyncClient:
        client.timeout = timeout
        return client

    return factory
