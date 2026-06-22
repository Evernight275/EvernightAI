from EvernightAI.application.agent import AgentApplication, AgentRunApplication
from EvernightAI.application.chat import ChatApplication
from EvernightAI.application.skill import SkillApplication
from EvernightAI.core.domain.interface import EvernightInterface
from EvernightAI.core.protocol.runtime import RuntimeProtocol


def create_interface(runtime: RuntimeProtocol) -> EvernightInterface:
    return EvernightInterface(
        runtime=runtime,
        chat=ChatApplication(runtime),
        agent=AgentApplication(runtime),
        agent_runs=AgentRunApplication(runtime),
        skills=SkillApplication(runtime),
    )
