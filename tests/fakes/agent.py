from EvernightAI.core.error.agent import AgentStateError
from EvernightAI.core.protocol.agent import (
    AgentRunStateRegisterProtocol,
    AgentTraceRegisterProtocol,
    ToolExecutionRegisterProtocol,
)
from EvernightAI.core.schema.agent import (
    AgentRunState,
    AgentTraceEvent,
    ToolExecutionAttempt,
)
from EvernightAI.core.schema.auth import PrincipalScope


class InMemoryAgentRunStateRegister(AgentRunStateRegisterProtocol):
    def __init__(self) -> None:
        self.states: dict[str, AgentRunState] = {}

    def save_state(
        self,
        state: AgentRunState,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None:
        self.states[state.run_id] = state

    def get_state(
        self,
        run_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> AgentRunState:
        try:
            return self.states[run_id]
        except KeyError as error:
            raise AgentStateError(
                f"The agent run state {run_id} is not found"
            ) from error

    def list_states(
        self,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> list[AgentRunState]:
        return list(self.states.values())

    def delete_state(
        self,
        run_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None:
        self.states.pop(run_id, None)


class InMemoryAgentTraceRegister(AgentTraceRegisterProtocol):
    def __init__(self) -> None:
        self.events: dict[str, list[AgentTraceEvent]] = {}

    def append_event(self, run_id: str, event: AgentTraceEvent) -> int:
        events = self.events.setdefault(run_id, [])
        sequence = len(events) + 1
        event.sequence = sequence
        events.append(event)
        return sequence

    def list_events(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
        limit: int | None = None,
    ) -> list[AgentTraceEvent]:
        events = [
            event
            for event in self.events.get(run_id, [])
            if event.sequence is not None and event.sequence > after_sequence
        ]
        return events if limit is None else events[:limit]

    def clear_events(self, run_id: str) -> None:
        self.events.pop(run_id, None)


class InMemoryToolExecutionRegister(ToolExecutionRegisterProtocol):
    def __init__(self) -> None:
        self.attempts: dict[tuple[str, str, int], ToolExecutionAttempt] = {}

    def create_attempt(
        self,
        attempt: ToolExecutionAttempt,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None:
        key = (attempt.run_id, attempt.tool_call_id, attempt.attempt)
        if key in self.attempts:
            raise AgentStateError("The tool execution attempt already exists")
        self.attempts[key] = attempt

    def save_attempt(
        self,
        attempt: ToolExecutionAttempt,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None:
        key = (attempt.run_id, attempt.tool_call_id, attempt.attempt)
        if key not in self.attempts:
            raise AgentStateError("The tool execution attempt is not found")
        self.attempts[key] = attempt

    def get_attempt(
        self,
        run_id: str,
        tool_call_id: str,
        attempt: int,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> ToolExecutionAttempt:
        try:
            return self.attempts[(run_id, tool_call_id, attempt)]
        except KeyError as error:
            raise AgentStateError(
                "The tool execution attempt is not found"
            ) from error

    def list_attempts(
        self,
        run_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> list[ToolExecutionAttempt]:
        return sorted(
            (
                attempt
                for attempt in self.attempts.values()
                if attempt.run_id == run_id
            ),
            key=lambda attempt: (attempt.tool_call_id, attempt.attempt),
        )
