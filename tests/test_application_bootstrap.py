from EvernightAI.application.agent import AgentApplication, AgentRunApplication
from EvernightAI.application.bootstrap import create_interface
from EvernightAI.application.chat import ChatApplication
from EvernightAI.core.domain.interface import EvernightInterface
from EvernightAI.core.protocol.interface import EvernightInterfaceProtocol
from EvernightAI.infra.bootstrap import create_runtime


def test_application_bootstrap_wraps_existing_runtime() -> None:
    runtime = create_runtime()

    interface = create_interface(runtime)

    assert isinstance(interface, EvernightInterface)
    assert isinstance(interface, EvernightInterfaceProtocol)
    assert interface.runtime is runtime
    assert isinstance(interface.chat, ChatApplication)
    assert isinstance(interface.agent, AgentApplication)
    assert isinstance(interface.agent_runs, AgentRunApplication)
