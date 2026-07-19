from EvernightAI.core.protocol.interface import (
    AgentInterfaceProtocol,
    AgentRunInterfaceProtocol,
    ChatInterfaceProtocol,
    DataAnalysisInterfaceProtocol,
    EvernightInterfaceProtocol,
    ProviderInterfaceProtocol,
    SessionInterfaceProtocol,
    SkillInterfaceProtocol,
    ToolInterfaceProtocol,
)
from EvernightAI.core.protocol.runtime import RuntimeProtocol


class EvernightInterface(EvernightInterfaceProtocol):
    def __init__(
        self,
        runtime: RuntimeProtocol,
        chat: ChatInterfaceProtocol,
        providers: ProviderInterfaceProtocol,
        tools: ToolInterfaceProtocol,
        data_analysis: DataAnalysisInterfaceProtocol,
        agent: AgentInterfaceProtocol,
        agent_runs: AgentRunInterfaceProtocol,
        skills: SkillInterfaceProtocol,
        sessions: SessionInterfaceProtocol,
    ) -> None:
        self._runtime = runtime
        self._chat = chat
        self._providers = providers
        self._tools = tools
        self._data_analysis = data_analysis
        self._agent = agent
        self._agent_runs = agent_runs
        self._skills = skills
        self._sessions = sessions

    @property
    def runtime(self) -> RuntimeProtocol:
        return self._runtime

    @property
    def chat(self) -> ChatInterfaceProtocol:
        return self._chat

    @property
    def providers(self) -> ProviderInterfaceProtocol:
        return self._providers

    @property
    def tools(self) -> ToolInterfaceProtocol:
        return self._tools

    @property
    def data_analysis(self) -> DataAnalysisInterfaceProtocol:
        return self._data_analysis

    @property
    def agent(self) -> AgentInterfaceProtocol:
        return self._agent

    @property
    def agent_runs(self) -> AgentRunInterfaceProtocol:
        return self._agent_runs

    @property
    def skills(self) -> SkillInterfaceProtocol:
        return self._skills

    @property
    def sessions(self) -> SessionInterfaceProtocol:
        return self._sessions

    async def initialize(self) -> None:
        await self._runtime.initialize()

    async def close(self) -> None:
        await self.agent_runs.close()
        await self._runtime.close()
