from EvernightAI.core.protocol.base import EvernightAIProtocol, RegisterProtocol
from EvernightAI.core.schema.agent import AgentRunState, AgentTraceEvent


class AgentProtocol(EvernightAIProtocol):
    """
    Agent协议
    """

    ...


class AgentRunStateRegisterProtocol(AgentProtocol, RegisterProtocol):
    """
    Agent运行状态注册协议
    """

    def save_state(self, state: AgentRunState) -> None: ...

    def get_state(self, run_id: str) -> AgentRunState: ...

    def list_states(self) -> list[AgentRunState]: ...

    def delete_state(self, run_id: str) -> None: ...


class AgentTraceRegisterProtocol(AgentProtocol, RegisterProtocol):
    """
    Agent追踪事件注册协议
    """

    def append_event(self, run_id: str, event: AgentTraceEvent) -> None: ...

    def list_events(self, run_id: str) -> list[AgentTraceEvent]: ...

    def clear_events(self, run_id: str) -> None: ...
