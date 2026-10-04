import json
from pathlib import Path

from EvernightAI.core.protocol.tool import ToolPolicyStoreProtocol
from EvernightAI.core.schema.auth import PrincipalScope
from EvernightAI.core.schema.tool import ToolAccessMode
from EvernightAI.infra.sqlite import SQLiteMigrationRunner, connect_sqlite


class SQLiteToolPolicyStore(ToolPolicyStoreProtocol):
    def __init__(self, database_path: str | Path) -> None:
        self._connection = connect_sqlite(database_path)
        SQLiteMigrationRunner(database_path).run(self._connection)

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
