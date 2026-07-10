from collections.abc import AsyncIterator, Awaitable, Callable

from EvernightAI.core.protocol.base import EvernightAIProtocol, RegisterProtocol
from EvernightAI.core.error.agent import AgentStateError
from EvernightAI.core.schema.agent import AgentRunState, AgentRunStatus, AgentTraceEvent
from EvernightAI.core.schema.auth import PrincipalScope


class AgentProtocol(EvernightAIProtocol):
    """
    Agent协议
    """

    ...


AgentRunOperation = Callable[[], Awaitable[AgentRunState]]
AgentRunStreamOperation = Callable[[], AsyncIterator[AgentTraceEvent]]


class AgentRunExecutorProtocol(AgentProtocol):
    async def execute(
        self,
        run_id: str,
        operation: AgentRunOperation,
        *,
        timeout_seconds: float | None = None,
    ) -> AgentRunState: ...

    def cancel(self, run_id: str) -> bool: ...

    def stream(
        self,
        run_id: str,
        operation: AgentRunStreamOperation,
        *,
        timeout_seconds: float | None = None,
    ) -> AsyncIterator[AgentTraceEvent]: ...

    async def close(self) -> None: ...


class AgentRunStateRegisterProtocol(AgentProtocol, RegisterProtocol):
    """
    Agent运行状态注册协议
    """

    def create_state(
        self,
        state: AgentRunState,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None:
        try:
            self.get_state(state.run_id, principal_scope=principal_scope)
        except AgentStateError:
            self.save_state(state, principal_scope=principal_scope)
            return
        raise AgentStateError(f"The agent run state {state.run_id} already exists")

    def save_state(
        self,
        state: AgentRunState,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None: ...

    def get_state(
        self,
        run_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> AgentRunState: ...

    def list_states(
        self,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> list[AgentRunState]: ...

    def query_states(
        self,
        *,
        cursor: str | None = None,
        limit: int | None = None,
        owner_id: str | None = None,
        status: AgentRunStatus | None = None,
        context_id: str | None = None,
        principal_scope: PrincipalScope | None = None,
    ) -> list[AgentRunState]:
        states = sorted(
            self.list_states(principal_scope=principal_scope),
            key=lambda state: state.run_id,
        )
        if cursor is not None:
            states = [state for state in states if state.run_id > cursor]
        if owner_id is not None:
            states = [state for state in states if state.owner_id == owner_id]
        if status is not None:
            states = [state for state in states if state.status is status]
        if context_id is not None:
            states = [state for state in states if state.request.context_id == context_id]
        return states if limit is None else states[:limit]

    def acquire_lease(
        self,
        run_id: str,
        lease_owner: str,
        *,
        ttl_seconds: float,
        principal_scope: PrincipalScope | None = None,
    ) -> int: ...

    def heartbeat_lease(
        self,
        run_id: str,
        lease_owner: str,
        generation: int,
        *,
        ttl_seconds: float,
        principal_scope: PrincipalScope | None = None,
    ) -> bool: ...

    def release_lease(
        self,
        run_id: str,
        lease_owner: str,
        generation: int,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None: ...

    def delete_state(
        self,
        run_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None: ...


class AgentTraceRegisterProtocol(AgentProtocol, RegisterProtocol):
    """
    Agent追踪事件注册协议
    """

    def append_event(self, run_id: str, event: AgentTraceEvent) -> int: ...

    def list_events(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
        limit: int | None = None,
    ) -> list[AgentTraceEvent]: ...

    def clear_events(self, run_id: str) -> None: ...

    def prune_events(
        self,
        *,
        older_than: str | None = None,
        keep_latest: int | None = None,
    ) -> int: ...
