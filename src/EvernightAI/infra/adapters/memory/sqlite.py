from pathlib import Path

from EvernightAI.core.error.memory import MemoryNotFoundError
from EvernightAI.core.protocol.memory import MemoryRegisterProtocol
from EvernightAI.core.schema.auth import PrincipalScope
from EvernightAI.core.schema.memory import MemoryItem, MemoryQuery
from EvernightAI.infra.sqlite import (
    SQLiteMigrationRunner,
    connect_sqlite,
    sqlite_transaction,
)


def _require_scope(
    memory: MemoryItem,
    principal_scope: PrincipalScope | None,
) -> None:
    if principal_scope is not None and not principal_scope.permits(memory.owner_id):
        raise MemoryNotFoundError(
            f"The memory {memory.memory_id} is not available in this scope"
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


class SQLiteMemoryRegister(MemoryRegisterProtocol):
    def __init__(self, database_path: str | Path) -> None:
        self._database_path = str(database_path)
        self._connection = connect_sqlite(self._database_path)
        SQLiteMigrationRunner(self._database_path).run(self._connection)

    def register(
        self,
        memory: MemoryItem,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None:
        """注册记忆"""
        _require_scope(memory, principal_scope)
        with sqlite_transaction(self._connection, immediate=True):
            self._connection.execute(
                """
                INSERT INTO memories (
                    memory_id, kind, scope, scope_id, is_enabled, owner_id,
                    relevance, confidence, expires_at, updated_at, payload
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(memory_id) DO UPDATE SET
                    kind = excluded.kind,
                    scope = excluded.scope,
                    scope_id = excluded.scope_id,
                    is_enabled = excluded.is_enabled,
                    owner_id = excluded.owner_id,
                    relevance = excluded.relevance,
                    confidence = excluded.confidence,
                    expires_at = excluded.expires_at,
                    updated_at = excluded.updated_at,
                    payload = excluded.payload
                """,
                (
                    memory.memory_id,
                    memory.kind.value,
                    memory.scope.value,
                    memory.scope_id,
                    int(memory.is_enabled),
                    memory.owner_id,
                    memory.relevance,
                    memory.confidence,
                    memory.expires_at.isoformat() if memory.expires_at else None,
                    memory.updated_at.isoformat(),
                    memory.model_dump_json(),
                ),
            )

    def unregister(
        self,
        memory_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None:
        """注销记忆"""
        where, values = _scoped_identity("memory_id", memory_id, principal_scope)
        with sqlite_transaction(self._connection, immediate=True):
            cursor = self._connection.execute(
                f"DELETE FROM memories WHERE {where}",
                values,
            )

        if cursor.rowcount == 0:
            raise MemoryNotFoundError(f"The memory {memory_id} is not registered")

    def get(
        self,
        memory_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> MemoryItem:
        """获取记忆"""
        where, values = _scoped_identity("memory_id", memory_id, principal_scope)
        cursor = self._connection.execute(
            f"SELECT payload FROM memories WHERE {where}",
            values,
        )
        row = cursor.fetchone()
        if row is None:
            raise MemoryNotFoundError(f"The memory {memory_id} is not found")

        payload: str = row[0]
        return MemoryItem.model_validate_json(payload)

    def has(
        self,
        memory_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> bool:
        """检查记忆是否存在"""
        where, values = _scoped_identity("memory_id", memory_id, principal_scope)
        cursor = self._connection.execute(
            f"SELECT 1 FROM memories WHERE {where}",
            values,
        )
        return cursor.fetchone() is not None

    def list_memories(
        self,
        *,
        cursor: str | None = None,
        limit: int | None = None,
        owner_id: str | None = None,
        query: MemoryQuery | None = None,
        principal_scope: PrincipalScope | None = None,
    ) -> list[MemoryItem]:
        """列出所有记忆"""
        where: list[str] = []
        values: list[object] = []
        if cursor is not None:
            where.append("memory_id > ?")
            values.append(cursor)
        if principal_scope is not None and principal_scope.owner_id is not None:
            if owner_id is not None and owner_id != principal_scope.owner_id:
                return []
            owner_id = principal_scope.owner_id
        if owner_id is not None:
            where.append("owner_id = ?")
            values.append(owner_id)
        if query is not None:
            if query.scope is not None:
                where.append("scope = ?")
                values.append(query.scope.value)
            if query.scope_id is not None:
                where.append("scope_id = ?")
                values.append(query.scope_id)
            if query.kinds:
                placeholders = ", ".join("?" for _ in query.kinds)
                where.append(f"kind IN ({placeholders})")
                values.extend(kind.value for kind in query.kinds)
            if query.minimum_relevance is not None:
                where.append("relevance >= ?")
                values.append(query.minimum_relevance)
            if query.minimum_confidence is not None:
                where.append("confidence >= ?")
                values.append(query.minimum_confidence)
        sql = "SELECT payload FROM memories"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY memory_id"
        effective_limit = limit if query is None else None
        if effective_limit is not None:
            sql += " LIMIT ?"
            values.append(effective_limit)
        rows = self._connection.execute(sql, values).fetchall()
        memories = [MemoryItem.model_validate_json(row[0]) for row in rows]
        if query is None:
            return memories
        from EvernightAI.core.domain.memory import select_memories

        selected = select_memories(memories, query).memories
        return selected if limit is None else selected[:limit]

    def close(self) -> None:
        """关闭数据库连接"""
        self._connection.close()

    def is_ready(self) -> bool:
        try:
            return self._connection.execute("SELECT 1").fetchone() == (1,)
        except Exception:
            return False
