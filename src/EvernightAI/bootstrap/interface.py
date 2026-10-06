from EvernightAI.application.agent import AgentApplication, AgentRunApplication
from EvernightAI.application.chat import ChatApplication
from EvernightAI.application.file import FileApplication
from EvernightAI.application.provider import ProviderApplication
from EvernightAI.application.session import SessionApplication
from EvernightAI.application.image_tool import ImageToolApplication
from EvernightAI.infra.registrations.tool.image import register_image_tool
from EvernightAI.core.domain.interface import EvernightInterface
from EvernightAI.core.protocol.runtime import RuntimeProtocol


def create_interface(runtime: RuntimeProtocol) -> EvernightInterface:
    if runtime.image_task_executor is not None and not runtime.tool_register.has(
        "generate_image"
    ):
        register_image_tool(
            runtime.tool_register, ImageToolApplication(runtime).execute
        )
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
        files=FileApplication(runtime),
    )
