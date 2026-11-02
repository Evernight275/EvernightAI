import json
from pathlib import Path

from EvernightAI.core.protocol.shell import ShellSessionStoreProtocol
from EvernightAI.core.protocol.tool import ToolPolicyStoreProtocol
from EvernightAI.core.schema.auth import PrincipalScope
from EvernightAI.core.schema.shell import ShellSessionState
from EvernightAI.core.schema.tool import ToolAccessMode
from EvernightAI.infra.sqlite import SQLiteStoreConnection


class SQLiteToolPolicyStore(ToolPolicyStoreProtocol):
    def __init__(self, database_path: str | Path) -> None:
        self._connection = SQLiteStoreConnection(database_path)

    def _owner_key(self, scope: PrincipalScope | None) -> str:
        return json.dumps(scope.owner_id if scope else None)

    def get(
        self, tool_name: str, *, principal_scope: PrincipalScope | None = None
    ) -> ToolAccessMode | None:
        row = self._connection.execute(
            "SELECT mode FROM tool_policies WHERE owner_key = ? AND tool_name = ?",
            (self._owner_key(principal_scope), tool_name),
        ).fetchone()
        return ToolAccessMode(row[0]) if row else None

    def set(
        self,
        tool_name: str,
        mode: ToolAccessMode,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None:
        self._connection.execute(
            "INSERT INTO tool_policies (owner_key, tool_name, mode) VALUES (?, ?, ?) ON CONFLICT(owner_key, tool_name) DO UPDATE SET mode = excluded.mode",
            (self._owner_key(principal_scope), tool_name, mode.value),
        )

    def delete(
        self, tool_name: str, *, principal_scope: PrincipalScope | None = None
    ) -> None:
        self._connection.execute(
            "DELETE FROM tool_policies WHERE owner_key = ? AND tool_name = ?",
            (self._owner_key(principal_scope), tool_name),
        )

    def is_ready(self) -> bool:
        try:
            return self._connection.execute("SELECT 1").fetchone() == (1,)
        except Exception:
            return False

    def close(self) -> None:
        self._connection.close()


class SQLiteShellSessionStore(ShellSessionStoreProtocol):
    def __init__(self, database_path: str | Path) -> None:
        self._connection = SQLiteStoreConnection(database_path)

    def _owner_key(self, scope: PrincipalScope | None) -> str:
        return json.dumps(scope.owner_id if scope else None)

    def get(
        self, session_key: str, *, principal_scope: PrincipalScope | None = None
    ) -> ShellSessionState | None:
        row = self._connection.execute(
            "SELECT payload FROM shell_sessions WHERE owner_key = ? AND session_key = ?",
            (self._owner_key(principal_scope), session_key),
        ).fetchone()
        return ShellSessionState.model_validate_json(row[0]) if row else None

    def save(
        self,
        state: ShellSessionState,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None:
        self._connection.execute(
            "INSERT INTO shell_sessions (owner_key, session_key, payload, updated_at) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(owner_key, session_key) DO UPDATE SET "
            "payload = excluded.payload, updated_at = excluded.updated_at",
            (
                self._owner_key(principal_scope),
                state.session_key,
                state.model_dump_json(),
                state.updated_at.isoformat() if state.updated_at else None,
            ),
        )

    def delete(
        self, session_key: str, *, principal_scope: PrincipalScope | None = None
    ) -> None:
        self._connection.execute(
            "DELETE FROM shell_sessions WHERE owner_key = ? AND session_key = ?",
            (self._owner_key(principal_scope), session_key),
        )

    def close(self) -> None:
        self._connection.close()
