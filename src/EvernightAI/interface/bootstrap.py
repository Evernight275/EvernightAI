from dataclasses import dataclass
from pathlib import Path

from EvernightAI.application.agent import AgentApplication, AgentRunApplication
from EvernightAI.application.chat import ChatApplication
from EvernightAI.core.protocol.runtime import RuntimeProtocol
from EvernightAI.infra.bootstrap import (
    create_runtime,
    create_sqlite_runtime,
)


@dataclass(frozen=True)
class EvernightInterface:
    runtime: RuntimeProtocol
    chat: ChatApplication
    agent: AgentApplication
    agent_runs: AgentRunApplication

    async def close(self) -> None:
        await self.runtime.close()


def create_interface(runtime: RuntimeProtocol) -> EvernightInterface:
    return EvernightInterface(
        runtime=runtime,
        chat=ChatApplication(runtime),
        agent=AgentApplication(runtime),
        agent_runs=AgentRunApplication(runtime),
    )


def create_in_memory_interface() -> EvernightInterface:
    return create_interface(create_runtime())


def create_sqlite_interface(
    database_path: str | Path,
    *,
    include_agent_storage: bool = True,
    filesystem_root: str | Path | None = None,
    max_read_chars: int = 12000,
    max_directory_entries: int = 100,
    allow_file_overwrite: bool = False,
    shell_allowed_commands: set[str] | None = None,
    shell_working_directory: str | Path | None = None,
    shell_timeout_seconds: float = 10.0,
    shell_max_output_chars: int = 12000,
) -> EvernightInterface:
    return create_interface(
        create_sqlite_runtime(
            database_path,
            include_agent_storage=include_agent_storage,
            filesystem_root=filesystem_root,
            max_read_chars=max_read_chars,
            max_directory_entries=max_directory_entries,
            allow_file_overwrite=allow_file_overwrite,
            shell_allowed_commands=shell_allowed_commands,
            shell_working_directory=shell_working_directory,
            shell_timeout_seconds=shell_timeout_seconds,
            shell_max_output_chars=shell_max_output_chars,
        )
    )
