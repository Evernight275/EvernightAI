from pathlib import Path
import sqlite3

from EvernightAI.core.error.memory import MemoryNotFoundError
from EvernightAI.core.protocol.memory import MemoryRegisterProtocol
from EvernightAI.core.schema.memory import MemoryItem


class SQLiteMemoryRegister(MemoryRegisterProtocol):
    def __init__(self, database_path: str | Path) -> None:
        self._database_path = str(database_path)
        if self._database_path != ":memory:":
            Path(self._database_path).parent.mkdir(parents=True, exist_ok=True)

        self._connection = sqlite3.connect(self._database_path)
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS memories (
                memory_id TEXT PRIMARY KEY,
                payload TEXT NOT NULL
            )
            """
        )
        self._connection.commit()

    def register(self, memory: MemoryItem) -> None:
        """注册记忆"""
        self._connection.execute(
            """
            INSERT INTO memories (memory_id, payload)
            VALUES (?, ?)
            ON CONFLICT(memory_id) DO UPDATE SET payload = excluded.payload
            """,
            (memory.memory_id, memory.model_dump_json()),
        )
        self._connection.commit()

    def unregister(self, memory_id: str) -> None:
        """注销记忆"""
        cursor = self._connection.execute(
            "DELETE FROM memories WHERE memory_id = ?",
            (memory_id,),
        )
        self._connection.commit()

        if cursor.rowcount == 0:
            raise MemoryNotFoundError(f"The memory {memory_id} is not registered")

    def get(self, memory_id: str) -> MemoryItem:
        """获取记忆"""
        cursor = self._connection.execute(
            "SELECT payload FROM memories WHERE memory_id = ?",
            (memory_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise MemoryNotFoundError(f"The memory {memory_id} is not found")

        payload: str = row[0]
        return MemoryItem.model_validate_json(payload)

    def has(self, memory_id: str) -> bool:
        """检查记忆是否存在"""
        cursor = self._connection.execute(
            "SELECT 1 FROM memories WHERE memory_id = ?",
            (memory_id,),
        )
        return cursor.fetchone() is not None

    def list_memories(self) -> list[MemoryItem]:
        """列出所有记忆"""
        cursor = self._connection.execute(
            "SELECT payload FROM memories ORDER BY memory_id",
        )
        return [MemoryItem.model_validate_json(row[0]) for row in cursor.fetchall()]

    def close(self) -> None:
        """关闭数据库连接"""
        self._connection.close()
