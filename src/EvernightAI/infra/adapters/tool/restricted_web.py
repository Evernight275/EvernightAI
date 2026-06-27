from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from EvernightAI.core.error.tool import ToolInputError
from EvernightAI.core.protocol.tool import ToolExecutorProtocol
from EvernightAI.core.schema.tool import (
    ToolDefinition,
    ToolPermission,
    ToolSafetyLevel,
)


class RestrictedHttpRequestTool:
    def __init__(
        self,
        *,
        allowed_hosts: set[str] | None = None,
        timeout_seconds: float = 10.0,
        max_response_chars: int = 12000,
    ) -> None:
        self._allowed_hosts = allowed_hosts
        self._timeout_seconds = timeout_seconds
        self._max_response_chars = max_response_chars

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="http_request",
            description="Send an allowlisted HTTP GET or POST request",
            parameters_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "method": {"type": "string", "enum": ["GET", "POST"]},
                    "headers": {
                        "type": "object",
                        "additionalProperties": {"type": "string"},
                    },
                    "body": {"type": "string"},
                    "json": {"type": "object"},
                },
                "required": ["url"],
            },
            permissions=[ToolPermission.NETWORK, ToolPermission.EXTERNAL_API],
            safety_level=ToolSafetyLevel.SENSITIVE,
            requires_approval=True,
            metadata={
                "allowed_hosts": _sorted_or_none(self._allowed_hosts),
                "timeout_seconds": self._timeout_seconds,
                "max_response_chars": self._max_response_chars,
            },
        )

    def executor(self) -> ToolExecutorProtocol:
        return self.execute

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        url = _parse_url(arguments.get("url"), self._allowed_hosts)
        method = _parse_method(arguments.get("method", "GET"))
        headers = _parse_headers(arguments.get("headers"))
        body = arguments.get("body")
        json_body = arguments.get("json")
        if body is not None and not isinstance(body, str):
            raise ToolInputError("The HTTP body must be a string")
        if method == "GET" and (body is not None or json_body is not None):
            raise ToolInputError("GET requests cannot include a body or json")

        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.request(
                method,
                url,
                headers=headers,
                content=body,
                json=json_body,
            )

        text = response.text
        truncated = len(text) > self._max_response_chars
        if truncated:
            text = text[: self._max_response_chars]

        return {
            "url": url,
            "method": method,
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "text": text,
            "truncated": truncated,
        }


class RestrictedScrapeWebPageTool:
    def __init__(
        self,
        *,
        allowed_hosts: set[str] | None = None,
        timeout_seconds: float = 10.0,
        max_text_chars: int = 12000,
    ) -> None:
        self._allowed_hosts = allowed_hosts
        self._timeout_seconds = timeout_seconds
        self._max_text_chars = max_text_chars

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="scrape_web_page",
            description="Fetch an allowlisted web page and extract readable text",
            parameters_schema={
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
            permissions=[ToolPermission.READ, ToolPermission.NETWORK],
            safety_level=ToolSafetyLevel.SENSITIVE,
            requires_approval=True,
            metadata={
                "allowed_hosts": _sorted_or_none(self._allowed_hosts),
                "timeout_seconds": self._timeout_seconds,
                "max_text_chars": self._max_text_chars,
            },
        )

    def executor(self) -> ToolExecutorProtocol:
        return self.execute

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        url = _parse_url(arguments.get("url"), self._allowed_hosts)
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.get(url)

        parser = _TextExtractor()
        parser.feed(response.text)
        text = " ".join(parser.text().split())
        truncated = len(text) > self._max_text_chars
        if truncated:
            text = text[: self._max_text_chars]

        return {
            "url": url,
            "status_code": response.status_code,
            "title": parser.title,
            "text": text,
            "truncated": truncated,
        }


class RestrictedDownloadFileTool:
    def __init__(
        self,
        *,
        output_directory: str | Path,
        allowed_hosts: set[str] | None = None,
        timeout_seconds: float = 10.0,
        max_bytes: int = 10_000_000,
    ) -> None:
        self._output_directory = Path(output_directory).resolve()
        self._allowed_hosts = allowed_hosts
        self._timeout_seconds = timeout_seconds
        self._max_bytes = max_bytes

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="download_file",
            description="Download an allowlisted URL to a fixed output directory",
            parameters_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "path": {"type": "string"},
                    "overwrite": {"type": "boolean"},
                },
                "required": ["url", "path"],
            },
            permissions=[
                ToolPermission.WRITE,
                ToolPermission.FILESYSTEM,
                ToolPermission.NETWORK,
            ],
            safety_level=ToolSafetyLevel.SENSITIVE,
            requires_approval=True,
            metadata={
                "output_directory": str(self._output_directory),
                "allowed_hosts": _sorted_or_none(self._allowed_hosts),
                "timeout_seconds": self._timeout_seconds,
                "max_bytes": self._max_bytes,
            },
        )

    def executor(self) -> ToolExecutorProtocol:
        return self.execute

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        url = _parse_url(arguments.get("url"), self._allowed_hosts)
        path = _resolve_output_path(self._output_directory, arguments.get("path"))
        overwrite = arguments.get("overwrite", False)
        if not isinstance(overwrite, bool):
            raise ToolInputError("The overwrite value must be a boolean")
        if path.exists() and not overwrite:
            raise ToolInputError(f"The file {path.name} already exists")

        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.get(url)

        content = response.content
        if len(content) > self._max_bytes:
            raise ToolInputError("The downloaded file exceeds max_bytes")

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return {
            "url": url,
            "path": path.relative_to(self._output_directory).as_posix(),
            "status_code": response.status_code,
            "bytes_written": len(content),
        }


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._hidden_depth = 0
        self._in_title = False
        self._parts: list[str] = []
        self.title: str | None = None

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag in {"script", "style", "noscript"}:
            self._hidden_depth += 1
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._hidden_depth:
            self._hidden_depth -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if not text:
            return
        if self._in_title:
            self.title = text if self.title is None else f"{self.title} {text}"
        if self._hidden_depth == 0:
            self._parts.append(text)

    def text(self) -> str:
        return "\n".join(self._parts)


def _parse_url(raw_url: object, allowed_hosts: set[str] | None) -> str:
    if not isinstance(raw_url, str) or not raw_url:
        raise ToolInputError("The url must be a non-empty string")

    parsed = urlparse(raw_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ToolInputError("The url must be an HTTP or HTTPS URL")
    if allowed_hosts is not None and parsed.hostname not in allowed_hosts:
        raise ToolInputError(f"The host {parsed.hostname} is not allowed")
    return raw_url


def _parse_method(raw_method: object) -> str:
    if not isinstance(raw_method, str):
        raise ToolInputError("The HTTP method must be a string")
    method = raw_method.upper()
    if method not in {"GET", "POST"}:
        raise ToolInputError("Only GET and POST are supported")
    return method


def _parse_headers(raw_headers: object) -> dict[str, str] | None:
    if raw_headers is None:
        return None
    if not isinstance(raw_headers, dict):
        raise ToolInputError("The headers value must be a dictionary")

    headers: dict[str, str] = {}
    for key, value in raw_headers.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ToolInputError("HTTP header names and values must be strings")
        headers[key] = value
    return headers


def _resolve_output_path(output_directory: Path, raw_path: object) -> Path:
    if not isinstance(raw_path, str) or not raw_path:
        raise ToolInputError("The output path must be a non-empty string")

    path = (output_directory / raw_path).resolve()
    try:
        path.relative_to(output_directory)
    except ValueError as exc:
        raise ToolInputError("The output path must stay inside the output directory") from exc
    return path


def _sorted_or_none(values: set[str] | None) -> list[str] | None:
    if values is None:
        return None
    return sorted(values)
