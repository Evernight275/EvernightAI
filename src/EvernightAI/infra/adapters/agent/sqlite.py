from datetime import datetime, timedelta, timezone
from pathlib import Path

from EvernightAI.core.error.agent import AgentStateError
from EvernightAI.core.protocol.agent import (
    AgentRunStateRegisterProtocol,
    AgentTraceRegisterProtocol,
)
from EvernightAI.core.schema.agent import AgentRunState, AgentRunStatus, AgentTraceEvent
from EvernightAI.core.schema.auth import PrincipalScope
from EvernightAI.infra.sqlite import (
    SQLiteMigrationRunner,
    connect_sqlite,
    sqlite_transaction,
)


def _require_scope(
    state: AgentRunState,
    principal_scope: PrincipalScope | None,
) -> None:
    if principal_scope is not None and not principal_scope.permits(state.owner_id):
        raise AgentStateError(
            f"The agent run state {state.run_id} is not available in this scope"
        )


def _scoped_identity(
    id_column: str,
    resource_id: str,
    principal_scope: PrincipalScope | None,
) -> tuple[str, tuple[object, ...]]:
    if principal_scope is None or principal_scope.owner_id is None:
        return f"{id_column} = ?", (resource_id,)
    return (
        f"{id_column} = ? AND owner_id = ?",
        (resource_id, principal_scope.owner_id),
    )


def _scope_sql(principal_scope: PrincipalScope | None) -> str:
    if principal_scope is None or principal_scope.owner_id is None:
        return ""
    return "AND owner_id = ?"


def _scope_values(
    principal_scope: PrincipalScope | None,
) -> tuple[object, ...]:
    if principal_scope is None or principal_scope.owner_id is None:
        return ()
    return (principal_scope.owner_id,)


class SQLiteAgentRunStateRegister(AgentRunStateRegisterProtocol):
    def __init__(self, database_path: str | Path) -> None:
        self._database_path = str(database_path)
        self._connection = connect_sqlite(self._database_path)
        SQLiteMigrationRunner(self._database_path).run(self._connection)

    def create_state(
        self,
        state: AgentRunState,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None:
        """原子创建Agent运行状态"""
        _require_scope(state, principal_scope)
        now = _utc_now_text()
        try:
            with sqlite_transaction(self._connection, immediate=True):
                self._connection.execute(
                    """
                    INSERT INTO agent_run_states (
                        run_id, status, context_id, owner_id, payload,
                        created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        state.run_id,
                        state.status.value,
                        state.request.context_id,
                        state.owner_id,
                        state.model_dump_json(),
                        now,
                        now,
                    ),
                )
        except Exception as exc:
            if "UNIQUE constraint failed" in str(exc):
                raise AgentStateError(
                    f"The agent run state {state.run_id} already exists"
                ) from exc
            raise

    def save_state(
        self,
        state: AgentRunState,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None:
        """保存Agent运行状态快照"""
        _require_scope(state, principal_scope)
        now = _utc_now_text()
        with sqlite_transaction(self._connection, immediate=True):
            self._connection.execute(
                """
                INSERT INTO agent_run_states (
                    run_id, status, context_id, owner_id, payload,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    status = excluded.status,
                    context_id = excluded.context_id,
                    owner_id = excluded.owner_id,
                    payload = excluded.payload,
                    updated_at = excluded.updated_at
                """,
                (
                    state.run_id,
                    state.status.value,
                    state.request.context_id,
                    state.owner_id,
                    state.model_dump_json(),
                    now,
                    now,
                ),
            )

    def get_state(
        self,
        run_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> AgentRunState:
        where, values = _scoped_identity("run_id", run_id, principal_scope)
        row = self._connection.execute(
            f"SELECT payload FROM agent_run_states WHERE {where}",
            values,
        ).fetchone()
        if row is None:
            raise AgentStateError(f"The agent run state {run_id} is not found")
        return AgentRunState.model_validate_json(row[0])

    def list_states(
        self,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> list[AgentRunState]:
        return self.query_states(principal_scope=principal_scope)

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
        where: list[str] = []
        values: list[object] = []
        if principal_scope is not None and principal_scope.owner_id is not None:
            if owner_id is not None and owner_id != principal_scope.owner_id:
                return []
            owner_id = principal_scope.owner_id
        filters = {
            "run_id > ?": cursor,
            "owner_id = ?": owner_id,
            "status = ?": status.value if status is not None else None,
            "context_id = ?": context_id,
        }
        for clause, value in filters.items():
            if value is not None:
                where.append(clause)
                values.append(value)
        sql = "SELECT payload FROM agent_run_states"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY run_id"
        if limit is not None:
            sql += " LIMIT ?"
            values.append(limit)
        rows = self._connection.execute(sql, values).fetchall()
        return [AgentRunState.model_validate_json(row[0]) for row in rows]

    def delete_state(
        self,
        run_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None:
        where, values = _scoped_identity("run_id", run_id, principal_scope)
        with sqlite_transaction(self._connection, immediate=True):
            cursor = self._connection.execute(
                f"DELETE FROM agent_run_states WHERE {where}",
                values,
            )
            if cursor.rowcount == 0:
                raise AgentStateError(
                    f"The agent run state {run_id} is not registered"
                )

    def acquire_lease(
        self,
        run_id: str,
        lease_owner: str,
        *,
        ttl_seconds: float,
        principal_scope: PrincipalScope | None = None,
    ) -> int:
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=ttl_seconds)
        with sqlite_transaction(self._connection, immediate=True):
            owner_clause = _scope_sql(principal_scope)
            cursor = self._connection.execute(
                f"""
                UPDATE agent_run_states
                SET lease_owner = ?, lease_expires_at = ?, heartbeat_at = ?,
                    lease_generation = lease_generation + 1
                WHERE run_id = ?
                  AND (lease_owner IS NULL OR lease_expires_at <= ? OR lease_owner = ?)
                  {owner_clause}
                """,
                (
                    lease_owner,
                    expires_at.isoformat(),
                    now.isoformat(),
                    run_id,
                    now.isoformat(),
                    lease_owner,
                    *_scope_values(principal_scope),
                ),
            )
            if cursor.rowcount != 1:
                where, values = _scoped_identity("run_id", run_id, principal_scope)
                if self._connection.execute(
                    f"SELECT 1 FROM agent_run_states WHERE {where}", values
                ).fetchone() is None:
                    raise AgentStateError(f"The agent run state {run_id} is not found")
                raise AgentStateError(f"The agent run {run_id} lease is held")
            row = self._connection.execute(
                "SELECT lease_generation FROM agent_run_states WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                raise AgentStateError(
                    f"The agent run {run_id} lease generation is unavailable"
                )
            return int(row[0])

    def heartbeat_lease(
        self,
        run_id: str,
        lease_owner: str,
        generation: int,
        *,
        ttl_seconds: float,
        principal_scope: PrincipalScope | None = None,
    ) -> bool:
        now = datetime.now(timezone.utc)
        with sqlite_transaction(self._connection, immediate=True):
            owner_clause = _scope_sql(principal_scope)
            cursor = self._connection.execute(
                f"""
                UPDATE agent_run_states
                SET heartbeat_at = ?, lease_expires_at = ?
                WHERE run_id = ? AND lease_owner = ? AND lease_generation = ?
                  {owner_clause}
                """,
                (
                    now.isoformat(),
                    (now + timedelta(seconds=ttl_seconds)).isoformat(),
                    run_id,
                    lease_owner,
                    generation,
                    *_scope_values(principal_scope),
                ),
            )
        return cursor.rowcount == 1

    def release_lease(
        self,
        run_id: str,
        lease_owner: str,
        generation: int,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None:
        with sqlite_transaction(self._connection, immediate=True):
            owner_clause = _scope_sql(principal_scope)
            self._connection.execute(
                f"""
                UPDATE agent_run_states
                SET lease_owner = NULL, lease_expires_at = NULL, heartbeat_at = NULL
                WHERE run_id = ? AND lease_owner = ? AND lease_generation = ?
                  {owner_clause}
                """,
                (
                    run_id,
                    lease_owner,
                    generation,
                    *_scope_values(principal_scope),
                ),
            )

    def close(self) -> None:
        self._connection.close()

    def is_ready(self) -> bool:
        try:
            return self._connection.execute("SELECT 1").fetchone() == (1,)
        except Exception:
            return False


class SQLiteAgentTraceRegister(AgentTraceRegisterProtocol):
    def __init__(self, database_path: str | Path) -> None:
        self._database_path = str(database_path)
        self._connection = connect_sqlite(self._database_path)
        SQLiteMigrationRunner(self._database_path).run(self._connection)

    def append_event(self, run_id: str, event: AgentTraceEvent) -> int:
        with sqlite_transaction(self._connection, immediate=True):
            row = self._connection.execute(
                """
                SELECT COALESCE(MAX(sequence), 0) + 1
                FROM agent_trace_events
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
            if row is None:
                raise AgentStateError(
                    f"The agent run {run_id} trace sequence is unavailable"
                )
            sequence = int(row[0])
            event.sequence = sequence
            self._connection.execute(
                """
                INSERT INTO agent_trace_events (run_id, sequence, payload, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (run_id, sequence, event.model_dump_json(), _utc_now_text()),
            )
        return sequence

    def list_events(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
        limit: int | None = None,
    ) -> list[AgentTraceEvent]:
        sql = """
            SELECT sequence, payload FROM agent_trace_events
            WHERE run_id = ? AND sequence > ?
            ORDER BY sequence
        """
        values: list[object] = [run_id, after_sequence]
        if limit is not None:
            sql += " LIMIT ?"
            values.append(limit)
        rows = self._connection.execute(sql, values).fetchall()
        events: list[AgentTraceEvent] = []
        for sequence, payload in rows:
            event = AgentTraceEvent.model_validate_json(payload)
            event.sequence = sequence
            events.append(event)
        return events

    def clear_events(self, run_id: str) -> None:
        with sqlite_transaction(self._connection, immediate=True):
            self._connection.execute(
                "DELETE FROM agent_trace_events WHERE run_id = ?",
                (run_id,),
            )

    def prune_events(
        self,
        *,
        older_than: str | None = None,
        keep_latest: int | None = None,
    ) -> int:
        deleted = 0
        with sqlite_transaction(self._connection, immediate=True):
            if older_than is not None:
                cursor = self._connection.execute(
                    "DELETE FROM agent_trace_events WHERE created_at < ?",
                    (older_than,),
                )
                deleted += cursor.rowcount
            if keep_latest is not None:
                cursor = self._connection.execute(
                    """
                    DELETE FROM agent_trace_events
                    WHERE event_id NOT IN (
                        SELECT event_id FROM agent_trace_events
                        ORDER BY event_id DESC LIMIT ?
                    )
                    """,
                    (keep_latest,),
                )
                deleted += cursor.rowcount
        return deleted

    def close(self) -> None:
        self._connection.close()

    def is_ready(self) -> bool:
        try:
            return self._connection.execute("SELECT 1").fetchone() == (1,)
        except Exception:
            return False


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat()
