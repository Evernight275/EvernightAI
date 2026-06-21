from EvernightAI.application.agent import AgentApplication, AgentRunApplication
from EvernightAI.application.chat import ChatApplication
from EvernightAI.interface.bootstrap import (
    EvernightInterface,
    create_in_memory_interface,
    create_interface,
    create_sqlite_interface,
)
from EvernightAI.infra.bootstrap import create_runtime


def test_interface_bootstrap_wraps_existing_runtime() -> None:
    runtime = create_runtime()

    interface = create_interface(runtime)

    assert isinstance(interface, EvernightInterface)
    assert interface.runtime is runtime
    assert isinstance(interface.chat, ChatApplication)
    assert isinstance(interface.agent, AgentApplication)
    assert isinstance(interface.agent_runs, AgentRunApplication)


def test_interface_bootstrap_creates_in_memory_interface() -> None:
    interface = create_in_memory_interface()

    assert isinstance(interface.chat, ChatApplication)
    assert interface.runtime.agent_state_register is None
    assert interface.runtime.agent_trace_register is None


def test_interface_bootstrap_creates_sqlite_interface(tmp_path) -> None:
    interface = create_sqlite_interface(
        tmp_path / "runtime.sqlite3",
        filesystem_root=tmp_path,
    )

    assert [tool.name for tool in interface.runtime.tools.list_tools()] == [
        "read_text_file",
        "write_text_file",
        "list_directory",
    ]
    assert interface.runtime.agent_state_register is not None
    assert interface.runtime.agent_trace_register is not None
