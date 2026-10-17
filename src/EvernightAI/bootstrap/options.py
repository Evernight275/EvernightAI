from dataclasses import dataclass
from pathlib import Path

from EvernightAI.core.protocol.context import (
    ContextSummarizerProtocol,
    ContextTokenEstimatorProtocol,
)


@dataclass(frozen=True)
class FilesystemToolOptions:
    root: str | Path
    max_read_chars: int = 12000
    max_directory_entries: int = 100
    max_search_results: int = 100
    allow_overwrite: bool = False


@dataclass(frozen=True)
class ShellToolOptions:
    allowed_commands: set[str]
    blocked_commands: set[str] | None = None
    working_directory: str | Path | None = None
    timeout_seconds: float = 10.0
    max_output_chars: int = 12000
    requires_approval: bool = True
    relaxed_approval: bool = False
    allowed_env_keys: set[str] | None = None


@dataclass(frozen=True)
class WebToolOptions:
    allowed_hosts: set[str] | None = None
    download_directory: str | Path | None = None
    timeout_seconds: float = 10.0
    max_response_chars: int = 12000
    max_download_bytes: int = 10_000_000


@dataclass(frozen=True)
class GitToolOptions:
    repository_directory: str | Path
    timeout_seconds: float = 10.0
    max_output_chars: int = 12000


@dataclass(frozen=True)
class ProjectToolOptions:
    working_directory: str | Path
    commands: dict[str, list[str]]
    command_overrides: dict[str, dict[str, list[str]]] | None = None
    timeout_seconds: float = 120.0
    max_output_chars: int = 20000


@dataclass(frozen=True)
class BuiltinToolOptions:
    """Built-in tools to register; a tool group is registered only when set."""

    filesystem: FilesystemToolOptions | None = None
    shell: ShellToolOptions | None = None
    web: WebToolOptions | None = None
    git: GitToolOptions | None = None
    project: ProjectToolOptions | None = None
    # Named project roots shared by the filesystem, Git and project tools.
    project_directories: dict[str, str | Path] | None = None


@dataclass(frozen=True)
class ContextStrategyOptions:
    max_messages: int | None = None
    max_tokens: int | None = None
    estimator: ContextTokenEstimatorProtocol | None = None
    enable_summary: bool = False
    summarizer: ContextSummarizerProtocol | None = None
    summarize_after_messages: int = 100
    keep_recent_messages: int = 20
