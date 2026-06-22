from pathlib import Path
import sqlite3

from EvernightAI.core.error.session import SessionNotFoundError
from EvernightAI.core.protocol.session import SessionRegisterProtocol
from EvernightAI.core.schema.session import Session


class SQLiteSessionRegister(SessionRegisterProtocol):
    def __init__(self, database_path: str | Path) -> None:
        self._database_path = str(database_path)
        if self._database_path != ":memory:":
            Path(self._database_path).parent.mkdir(parents=True, exist_ok=True)

        self._connection = sqlite3.connect(self._database_path)
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                payload TEXT NOT NULL
            )
            """
        )
        self._connection.commit()

    def register(self, session: Session) -> None:
        """注册会话"""
        self._connection.execute(
            """
            INSERT INTO sessions (session_id, payload)
            VALUES (?, ?)
            ON CONFLICT(session_id) DO UPDATE SET payload = excluded.payload
            """,
            (session.session_id, session.model_dump_json()),
        )
        self._connection.commit()

    def unregister(self, session_id: str) -> None:
        """注销会话"""
        cursor = self._connection.execute(
            "DELETE FROM sessions WHERE session_id = ?",
            (session_id,),
        )
        self._connection.commit()

        if cursor.rowcount == 0:
            raise SessionNotFoundError(f"The session {session_id} is not registered")

    def get(self, session_id: str) -> Session:
        """获取会话"""
        cursor = self._connection.execute(
            "SELECT payload FROM sessions WHERE session_id = ?",
            (session_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise SessionNotFoundError(f"The session {session_id} is not found")

        payload: str = row[0]
        return Session.model_validate_json(payload)

    def has(self, session_id: str) -> bool:
        """检查会话是否存在"""
        cursor = self._connection.execute(
            "SELECT 1 FROM sessions WHERE session_id = ?",
            (session_id,),
        )
        return cursor.fetchone() is not None

    def list_sessions(self) -> list[Session]:
        """列出所有会话"""
        cursor = self._connection.execute(
            "SELECT payload FROM sessions ORDER BY session_id",
        )
        return [Session.model_validate_json(row[0]) for row in cursor.fetchall()]

    def close(self) -> None:
        """关闭数据库连接"""
        self._connection.close()
