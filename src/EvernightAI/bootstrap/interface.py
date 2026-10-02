from EvernightAI.application.agent import AgentApplication, AgentRunApplication
from EvernightAI.application.chat import ChatApplication
from EvernightAI.application.provider import ProviderApplication
from EvernightAI.application.session import SessionApplication
from EvernightAI.core.domain.authorized_interface import AuthorizedEvernightInterface
from EvernightAI.core.domain.interface import EvernightInterface
from EvernightAI.core.protocol.auth import AuthorizerProtocol
from EvernightAI.core.protocol.interface import EvernightInterfaceProtocol
from EvernightAI.core.protocol.runtime import RuntimeProtocol
from EvernightAI.core.schema.auth import Principal


def create_interface(runtime: RuntimeProtocol) -> EvernightInterface:
    agent = AgentApplication(runtime)
    return EvernightInterface(
        runtime=runtime,
        chat=ChatApplication(runtime),
        providers=ProviderApplication(runtime),
        tools=runtime.tools,
        data_analysis=runtime.data_analysis,
        agent=agent,
        agent_runs=AgentRunApplication(runtime, agent=agent),
        skills=runtime.skills,
        sessions=SessionApplication(runtime),
    )


def create_authorized_interface(
    interface: EvernightInterfaceProtocol,
    authorizer: AuthorizerProtocol,
    principal: Principal,
) -> AuthorizedEvernightInterface:
    return AuthorizedEvernightInterface(interface, authorizer, principal)
