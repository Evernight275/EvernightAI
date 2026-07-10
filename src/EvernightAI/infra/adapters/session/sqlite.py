from pathlib import Path

from EvernightAI.core.error.session import SessionNotFoundError
from EvernightAI.core.protocol.session import SessionRegisterProtocol
from EvernightAI.core.schema.auth import PrincipalScope
from EvernightAI.core.schema.session import Session, SessionStatus
from EvernightAI.infra.sqlite import (
    SQLiteMigrationRunner,
    connect_sqlite,
    sqlite_transaction,
)


def _require_scope(
    session: Session,
    principal_scope: PrincipalScope | None,
) -> None:
    if principal_scope is not None and not principal_scope.permits(session.owner_id):
        raise SessionNotFoundError(
            f"The session {session.session_id} is not available in this scope"
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


class SQLiteSessionRegister(SessionRegisterProtocol):
    def __init__(self, database_path: str | Path) -> None:
        self._database_path = str(database_path)
        self._connection = connect_sqlite(self._database_path)
        SQLiteMigrationRunner(self._database_path).run(self._connection)

    def register(
        self,
        session: Session,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None:
        """注册会话"""
        _require_scope(session, principal_scope)
        with sqlite_transaction(self._connection, immediate=True):
            self._connection.execute(
                """
                INSERT INTO sessions (
                    session_id, status, provider_id, model_id, updated_at,
                    owner_id, payload
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    status = excluded.status,
                    provider_id = excluded.provider_id,
                    model_id = excluded.model_id,
                    updated_at = excluded.updated_at,
                    owner_id = excluded.owner_id,
                    payload = excluded.payload
                """,
                (
                    session.session_id,
                    session.status.value,
                    session.provider_id,
                    session.model_id,
                    session.updated_at.isoformat(),
                    session.owner_id,
                    session.model_dump_json(),
                ),
            )

    def unregister(
        self,
        session_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None:
        """注销会话"""
        where, values = _scoped_identity("session_id", session_id, principal_scope)
        with sqlite_transaction(self._connection, immediate=True):
            cursor = self._connection.execute(
                f"DELETE FROM sessions WHERE {where}",
                values,
            )

        if cursor.rowcount == 0:
            raise SessionNotFoundError(f"The session {session_id} is not registered")

    def get(
        self,
        session_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> Session:
        """获取会话"""
        where, values = _scoped_identity("session_id", session_id, principal_scope)
        cursor = self._connection.execute(
            f"SELECT payload FROM sessions WHERE {where}",
            values,
        )
        row = cursor.fetchone()
        if row is None:
            raise SessionNotFoundError(f"The session {session_id} is not found")

        payload: str = row[0]
        return Session.model_validate_json(payload)

    def has(
        self,
        session_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> bool:
        """检查会话是否存在"""
        where, values = _scoped_identity("session_id", session_id, principal_scope)
        cursor = self._connection.execute(
            f"SELECT 1 FROM sessions WHERE {where}",
            values,
        )
        return cursor.fetchone() is not None

    def list_sessions(
        self,
        *,
        cursor: str | None = None,
        limit: int | None = None,
        owner_id: str | None = None,
        status: SessionStatus | None = None,
        provider_id: str | None = None,
        model_id: str | None = None,
        principal_scope: PrincipalScope | None = None,
    ) -> list[Session]:
        """列出所有会话"""
        where: list[str] = []
        values: list[object] = []
        if principal_scope is not None and principal_scope.owner_id is not None:
            if owner_id is not None and owner_id != principal_scope.owner_id:
                return []
            owner_id = principal_scope.owner_id
        filters = {
            "session_id > ?": cursor,
            "owner_id = ?": owner_id,
            "status = ?": status.value if status is not None else None,
            "provider_id = ?": provider_id,
            "model_id = ?": model_id,
        }
        for clause, value in filters.items():
            if value is not None:
                where.append(clause)
                values.append(value)
        sql = "SELECT payload FROM sessions"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY session_id"
        if limit is not None:
            sql += " LIMIT ?"
            values.append(limit)
        rows = self._connection.execute(sql, values).fetchall()
        return [Session.model_validate_json(row[0]) for row in rows]

    def close(self) -> None:
        """关闭数据库连接"""
        self._connection.close()

    def is_ready(self) -> bool:
        try:
            return self._connection.execute("SELECT 1").fetchone() == (1,)
        except Exception:
            return False
