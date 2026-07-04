from EvernightAI.application.agent import AgentApplication, AgentRunApplication
from EvernightAI.application.chat import ChatApplication
from EvernightAI.application.data_analysis import DataAnalysisApplication
from EvernightAI.application.provider import ProviderApplication
from EvernightAI.application.session import SessionApplication
from EvernightAI.application.skill import SkillApplication
from EvernightAI.application.tool import ToolApplication
from EvernightAI.core.domain.authorized_interface import AuthorizedEvernightInterface
from EvernightAI.core.domain.interface import EvernightInterface
from EvernightAI.core.protocol.auth import AuthorizerProtocol
from EvernightAI.core.protocol.interface import EvernightInterfaceProtocol
from EvernightAI.core.protocol.runtime import RuntimeProtocol
from EvernightAI.core.schema.auth import Principal


def create_interface(runtime: RuntimeProtocol) -> EvernightInterface:
    return EvernightInterface(
        runtime=runtime,
        chat=ChatApplication(runtime),
        providers=ProviderApplication(runtime),
        tools=ToolApplication(runtime),
        data_analysis=DataAnalysisApplication(runtime),
        agent=AgentApplication(runtime),
        agent_runs=AgentRunApplication(runtime),
        skills=SkillApplication(runtime),
        sessions=SessionApplication(runtime),
    )


def create_authorized_interface(
    interface: EvernightInterfaceProtocol,
    authorizer: AuthorizerProtocol,
    principal: Principal,
) -> AuthorizedEvernightInterface:
    return AuthorizedEvernightInterface(interface, authorizer, principal)
