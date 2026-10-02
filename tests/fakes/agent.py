from datetime import datetime, timedelta, timezone

from EvernightAI.core.error.agent import AgentStateError
from EvernightAI.core.protocol.agent import (
    AgentRunStateRegisterProtocol,
    AgentTraceRegisterProtocol,
    ToolExecutionRegisterProtocol,
)
from EvernightAI.core.schema.agent import (
    AgentRunLease,
    AgentRunState,
    AgentTraceEvent,
    ToolExecutionAttempt,
)
from EvernightAI.core.schema.auth import PrincipalScope


class InMemoryAgentRunStateRegister(AgentRunStateRegisterProtocol):
    def __init__(self) -> None:
        self.states: dict[str, AgentRunState] = {}
        self.leases: dict[str, AgentRunLease] = {}
        self.lease_generations: dict[str, int] = {}

    def save_state(
        self,
        state: AgentRunState,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None:
        self.states[state.run_id] = state.model_copy(deep=True)

    def get_state(
        self,
        run_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> AgentRunState:
        try:
            return self.states[run_id].model_copy(deep=True)
        except KeyError as error:
            raise AgentStateError(
                f"The agent run state {run_id} is not found"
            ) from error

    def list_states(
        self,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> list[AgentRunState]:
        return [state.model_copy(deep=True) for state in self.states.values()]

    def delete_state(
        self,
        run_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None:
        self.states.pop(run_id, None)
        self.leases.pop(run_id, None)
        self.lease_generations.pop(run_id, None)

    def acquire_lease(
        self,
        run_id: str,
        lease_owner: str,
        *,
        ttl_seconds: float,
        principal_scope: PrincipalScope | None = None,
    ) -> int:
        self.get_state(run_id, principal_scope=principal_scope)
        now = datetime.now(timezone.utc)
        lease = self.leases.get(run_id)
        if (
            lease is not None
            and lease.owner != lease_owner
            and (lease.expires_at is None or lease.expires_at > now)
        ):
            raise AgentStateError(f"The agent run {run_id} lease is held")
        generation = self.lease_generations.get(run_id, 0) + 1
        self.lease_generations[run_id] = generation
        self.leases[run_id] = AgentRunLease(
            owner=lease_owner,
            expires_at=now + timedelta(seconds=ttl_seconds),
            heartbeat_at=now,
            generation=generation,
        )
        return generation

    def heartbeat_lease(
        self,
        run_id: str,
        lease_owner: str,
        generation: int,
        *,
        ttl_seconds: float,
        principal_scope: PrincipalScope | None = None,
    ) -> bool:
        lease = self.leases.get(run_id)
        if (
            lease is None
            or lease.owner != lease_owner
            or lease.generation != generation
        ):
            return False
        now = datetime.now(timezone.utc)
        lease.heartbeat_at = now
        lease.expires_at = now + timedelta(seconds=ttl_seconds)
        return True

    def release_lease(
        self,
        run_id: str,
        lease_owner: str,
        generation: int,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None:
        lease = self.leases.get(run_id)
        if (
            lease is not None
            and lease.owner == lease_owner
            and lease.generation == generation
        ):
            self.leases.pop(run_id)

    def get_execution_lease(
        self,
        run_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> AgentRunLease | None:
        self.get_state(run_id, principal_scope=principal_scope)
        lease = self.leases.get(run_id)
        return lease.model_copy(deep=True) if lease is not None else None

    def clear_execution_lease(
        self,
        run_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None:
        self.get_state(run_id, principal_scope=principal_scope)
        self.leases.pop(run_id, None)


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

    def prune_events(
        self,
        *,
        older_than: str | None = None,
        keep_latest: int | None = None,
    ) -> int:
        raise NotImplementedError("This test register does not support trace pruning")


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
            raise AgentStateError("The tool execution attempt is not found") from error

    def list_attempts(
        self,
        run_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> list[ToolExecutionAttempt]:
        return sorted(
            (attempt for attempt in self.attempts.values() if attempt.run_id == run_id),
            key=lambda attempt: (attempt.tool_call_id, attempt.attempt),
        )
