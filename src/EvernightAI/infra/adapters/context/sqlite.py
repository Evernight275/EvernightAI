from pathlib import Path
import sqlite3

from EvernightAI.core.error.context import ContextNotFoundError
from EvernightAI.core.protocol.context import ContextRegisterProtocol
from EvernightAI.core.schema.context import Context


class SQLiteContextRegister(ContextRegisterProtocol):
    def __init__(self, database_path: str | Path) -> None:
        self._database_path = str(database_path)
        if self._database_path != ":memory:":
            Path(self._database_path).parent.mkdir(parents=True, exist_ok=True)

        self._connection = sqlite3.connect(self._database_path)
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS contexts (
                context_id TEXT PRIMARY KEY,
                payload TEXT NOT NULL
            )
            """
        )
        self._connection.commit()

    def register(self, context: Context) -> None:
        """注册上下文"""
        self._connection.execute(
            """
            INSERT INTO contexts (context_id, payload)
            VALUES (?, ?)
            ON CONFLICT(context_id) DO UPDATE SET payload = excluded.payload
            """,
            (context.context_id, context.model_dump_json()),
        )
        self._connection.commit()

    def unregister(self, context_id: str) -> None:
        """注销上下文"""
        cursor = self._connection.execute(
            "DELETE FROM contexts WHERE context_id = ?",
            (context_id,),
        )
        self._connection.commit()

        if cursor.rowcount == 0:
            raise ContextNotFoundError(f"The context {context_id} is not registered")

    def get(self, context_id: str) -> Context:
        """获取上下文"""
        cursor = self._connection.execute(
            "SELECT payload FROM contexts WHERE context_id = ?",
            (context_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise ContextNotFoundError(f"The context {context_id} is not found")

        payload: str = row[0]
        return Context.model_validate_json(payload)

    def has(self, context_id: str) -> bool:
        """检查上下文是否存在"""
        cursor = self._connection.execute(
            "SELECT 1 FROM contexts WHERE context_id = ?",
            (context_id,),
        )
        return cursor.fetchone() is not None

    def list_contexts(self) -> list[Context]:
        """列出所有上下文"""
        cursor = self._connection.execute(
            "SELECT payload FROM contexts ORDER BY context_id",
        )
        return [Context.model_validate_json(row[0]) for row in cursor.fetchall()]

    def close(self) -> None:
        """关闭数据库连接"""
        self._connection.close()
