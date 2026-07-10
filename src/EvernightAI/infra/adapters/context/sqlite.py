from pathlib import Path

from EvernightAI.core.error.context import ContextNotFoundError, ContextStateError
from EvernightAI.core.protocol.context import ContextRegisterProtocol
from EvernightAI.core.schema.content import Content
from EvernightAI.core.schema.context import Context
from EvernightAI.core.schema.auth import PrincipalScope
from EvernightAI.infra.sqlite import (
    SQLiteMigrationRunner,
    connect_sqlite,
    sqlite_transaction,
)


def _require_scope(
    context: Context,
    principal_scope: PrincipalScope | None,
) -> None:
    if principal_scope is not None and not principal_scope.permits(context.owner_id):
        raise ContextNotFoundError(
            f"The context {context.context_id} is not available in this scope"
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


class SQLiteContextRegister(ContextRegisterProtocol):
    def __init__(self, database_path: str | Path) -> None:
        self._database_path = str(database_path)
        self._connection = connect_sqlite(self._database_path)
        SQLiteMigrationRunner(self._database_path).run(self._connection)

    def register(
        self,
        context: Context,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None:
        """注册上下文"""
        _require_scope(context, principal_scope)
        with sqlite_transaction(self._connection, immediate=True):
            self._connection.execute(
                """
                INSERT INTO contexts (context_id, revision, owner_id, payload)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(context_id) DO UPDATE SET
                    revision = excluded.revision,
                    owner_id = excluded.owner_id,
                    payload = excluded.payload
                """,
                (
                    context.context_id,
                    context.revision,
                    context.owner_id,
                    context.model_dump_json(),
                ),
            )

    def unregister(
        self,
        context_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None:
        """注销上下文"""
        where, values = _scoped_identity(
            "context_id",
            context_id,
            principal_scope,
        )
        with sqlite_transaction(self._connection, immediate=True):
            cursor = self._connection.execute(
                f"DELETE FROM contexts WHERE {where}",
                values,
            )

        if cursor.rowcount == 0:
            raise ContextNotFoundError(f"The context {context_id} is not registered")

    def get(
        self,
        context_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> Context:
        """获取上下文"""
        where, values = _scoped_identity(
            "context_id",
            context_id,
            principal_scope,
        )
        cursor = self._connection.execute(
            f"SELECT payload FROM contexts WHERE {where}",
            values,
        )
        row = cursor.fetchone()
        if row is None:
            raise ContextNotFoundError(f"The context {context_id} is not found")

        payload: str = row[0]
        return Context.model_validate_json(payload)

    def has(
        self,
        context_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> bool:
        """检查上下文是否存在"""
        where, values = _scoped_identity(
            "context_id",
            context_id,
            principal_scope,
        )
        cursor = self._connection.execute(
            f"SELECT 1 FROM contexts WHERE {where}",
            values,
        )
        return cursor.fetchone() is not None

    def list_contexts(
        self,
        *,
        cursor: str | None = None,
        limit: int | None = None,
        owner_id: str | None = None,
        principal_scope: PrincipalScope | None = None,
    ) -> list[Context]:
        """列出所有上下文"""
        where: list[str] = []
        values: list[object] = []
        if cursor is not None:
            where.append("context_id > ?")
            values.append(cursor)
        if principal_scope is not None and principal_scope.owner_id is not None:
            if owner_id is not None and owner_id != principal_scope.owner_id:
                return []
            owner_id = principal_scope.owner_id
        if owner_id is not None:
            where.append("owner_id = ?")
            values.append(owner_id)
        sql = "SELECT payload FROM contexts"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY context_id"
        if limit is not None:
            sql += " LIMIT ?"
            values.append(limit)
        rows = self._connection.execute(sql, values).fetchall()
        return [Context.model_validate_json(row[0]) for row in rows]

    def append_message(
        self,
        context_id: str,
        message: Content,
        *,
        expected_revision: int | None = None,
        principal_scope: PrincipalScope | None = None,
    ) -> Context:
        where, identity_values = _scoped_identity(
            "context_id",
            context_id,
            principal_scope,
        )
        with sqlite_transaction(self._connection, immediate=True):
            row = self._connection.execute(
                f"SELECT revision, payload FROM contexts WHERE {where}",
                identity_values,
            ).fetchone()
            if row is None:
                raise ContextNotFoundError(f"The context {context_id} is not found")
            revision = int(row[0])
            if expected_revision is not None and revision != expected_revision:
                raise ContextStateError(
                    f"The context {context_id} revision is {revision}, "
                    f"expected {expected_revision}"
                )
            context = Context.model_validate_json(row[1])
            updated = context.model_copy(
                update={
                    "messages": [*context.messages, message],
                    "revision": revision + 1,
                }
            )
            write = self._connection.execute(
                """
                UPDATE contexts
                SET revision = ?, owner_id = ?, payload = ?
                WHERE context_id = ? AND revision = ?
                """,
                (
                    updated.revision,
                    updated.owner_id,
                    updated.model_dump_json(),
                    context_id,
                    revision,
                ),
            )
            if write.rowcount != 1:
                raise ContextStateError(
                    f"The context {context_id} changed while appending"
                )
        return updated

    def close(self) -> None:
        """关闭数据库连接"""
        self._connection.close()

    def is_ready(self) -> bool:
        try:
            return self._connection.execute("SELECT 1").fetchone() == (1,)
        except Exception:
            return False
