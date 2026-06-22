from EvernightAI.core.protocol.interface import (
    AgentInterfaceProtocol,
    AgentRunInterfaceProtocol,
    ChatInterfaceProtocol,
    EvernightInterfaceProtocol,
    SkillInterfaceProtocol,
)
from EvernightAI.core.protocol.runtime import RuntimeProtocol


class EvernightInterface(EvernightInterfaceProtocol):
    def __init__(
        self,
        runtime: RuntimeProtocol,
        chat: ChatInterfaceProtocol,
        agent: AgentInterfaceProtocol,
        agent_runs: AgentRunInterfaceProtocol,
        skills: SkillInterfaceProtocol,
    ) -> None:
        self._runtime = runtime
        self._chat = chat
        self._agent = agent
        self._agent_runs = agent_runs
        self._skills = skills

    @property
    def runtime(self) -> RuntimeProtocol:
        return self._runtime

    @property
    def chat(self) -> ChatInterfaceProtocol:
        return self._chat

    @property
    def agent(self) -> AgentInterfaceProtocol:
        return self._agent

    @property
    def agent_runs(self) -> AgentRunInterfaceProtocol:
        return self._agent_runs

    @property
    def skills(self) -> SkillInterfaceProtocol:
        return self._skills

    async def close(self) -> None:
        await self.runtime.close()
