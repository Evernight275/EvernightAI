from pathlib import Path

from EvernightAI.core.protocol.tool import ToolRegisterProtocol
from EvernightAI.infra.adapters.tool.restricted_web import (
    RestrictedDownloadFileTool,
    RestrictedHttpRequestTool,
    RestrictedScrapeWebPageTool,
)


def register_restricted_web_tools(
    register: ToolRegisterProtocol,
    *,
    allowed_hosts: set[str] | None = None,
    download_directory: str | Path | None = None,
    timeout_seconds: float = 10.0,
    max_response_chars: int = 12000,
    max_download_bytes: int = 10_000_000,
) -> None:
    request_tool = RestrictedHttpRequestTool(
        allowed_hosts=allowed_hosts,
        timeout_seconds=timeout_seconds,
        max_response_chars=max_response_chars,
    )
    scrape_tool = RestrictedScrapeWebPageTool(
        allowed_hosts=allowed_hosts,
        timeout_seconds=timeout_seconds,
        max_text_chars=max_response_chars,
    )

    register.register(request_tool.definition, request_tool.executor())
    register.register(scrape_tool.definition, scrape_tool.executor())

    if download_directory is not None:
        download_tool = RestrictedDownloadFileTool(
            output_directory=download_directory,
            allowed_hosts=allowed_hosts,
            timeout_seconds=timeout_seconds,
            max_bytes=max_download_bytes,
        )
        register.register(download_tool.definition, download_tool.executor())
