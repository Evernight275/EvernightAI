from typing import Any

from EvernightAI.bootstrap.interface import create_interface
from EvernightAI.bootstrap.runtime import create_sqlite_runtime
from EvernightAI.core.domain.runtime import RuntimeKernel
from EvernightAI.core.protocol.interface import EvernightInterfaceProtocol
from EvernightAI.interface.cli.schema import EvernightConfig


def create_runtime_from_config(config: EvernightConfig) -> RuntimeKernel:
    return create_sqlite_runtime(
        config.runtime.database_path,
        **_runtime_tool_options(config),
    )


def create_interface_from_config(
    config: EvernightConfig,
) -> EvernightInterfaceProtocol:
    runtime = create_runtime_from_config(config)
    return create_interface(runtime)


def _runtime_tool_options(config: EvernightConfig) -> dict[str, Any]:
    filesystem = config.tools.filesystem
    shell = config.tools.shell
    return {
        "filesystem_root": filesystem.root if filesystem.enabled else None,
        "max_read_chars": filesystem.max_read_chars,
        "max_directory_entries": filesystem.max_directory_entries,
        "allow_file_overwrite": filesystem.allow_write,
        "shell_allowed_commands": (
            set(shell.allowed_commands) if shell.enabled else None
        ),
        "shell_working_directory": shell.working_directory,
        "shell_timeout_seconds": shell.timeout_seconds,
        "shell_max_output_chars": shell.max_output_chars,
    }
