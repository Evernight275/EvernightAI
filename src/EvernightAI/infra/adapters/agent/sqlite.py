from pathlib import Path
import sqlite3

from EvernightAI.core.error.agent import AgentStateError
from EvernightAI.core.protocol.agent import (
    AgentRunStateRegisterProtocol,
    AgentTraceRegisterProtocol,
)
from EvernightAI.core.schema.agent import AgentRunState, AgentTraceEvent


class SQLiteAgentRunStateRegister(AgentRunStateRegisterProtocol):
    def __init__(self, database_path: str | Path) -> None:
        self._database_path = str(database_path)
        if self._database_path != ":memory:":
            Path(self._database_path).parent.mkdir(parents=True, exist_ok=True)

        self._connection = sqlite3.connect(self._database_path)
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_run_states (
                run_id TEXT PRIMARY KEY,
                payload TEXT NOT NULL
            )
            """
        )
        self._connection.commit()

    def save_state(self, state: AgentRunState) -> None:
        """保存Agent运行状态"""
        self._connection.execute(
            """
            INSERT INTO agent_run_states (run_id, payload)
            VALUES (?, ?)
            ON CONFLICT(run_id) DO UPDATE SET payload = excluded.payload
            """,
            (state.run_id, state.model_dump_json()),
        )
        self._connection.commit()

    def get_state(self, run_id: str) -> AgentRunState:
        """获取Agent运行状态"""
        cursor = self._connection.execute(
            "SELECT payload FROM agent_run_states WHERE run_id = ?",
            (run_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise AgentStateError(f"The agent run state {run_id} is not found")

        payload: str = row[0]
        return AgentRunState.model_validate_json(payload)

    def list_states(self) -> list[AgentRunState]:
        """列出Agent运行状态"""
        cursor = self._connection.execute(
            "SELECT payload FROM agent_run_states ORDER BY run_id",
        )
        return [AgentRunState.model_validate_json(row[0]) for row in cursor.fetchall()]

    def delete_state(self, run_id: str) -> None:
        """删除Agent运行状态"""
        cursor = self._connection.execute(
            "DELETE FROM agent_run_states WHERE run_id = ?",
            (run_id,),
        )
        self._connection.commit()
        if cursor.rowcount == 0:
            raise AgentStateError(f"The agent run state {run_id} is not registered")

    def close(self) -> None:
        """关闭数据库连接"""
        self._connection.close()


class SQLiteAgentTraceRegister(AgentTraceRegisterProtocol):
    def __init__(self, database_path: str | Path) -> None:
        self._database_path = str(database_path)
        if self._database_path != ":memory:":
            Path(self._database_path).parent.mkdir(parents=True, exist_ok=True)

        self._connection = sqlite3.connect(self._database_path)
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_trace_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                payload TEXT NOT NULL
            )
            """
        )
        self._connection.commit()

    def append_event(self, run_id: str, event: AgentTraceEvent) -> None:
        """追加Agent追踪事件"""
        self._connection.execute(
            """
            INSERT INTO agent_trace_events (run_id, payload)
            VALUES (?, ?)
            """,
            (run_id, event.model_dump_json()),
        )
        self._connection.commit()

    def list_events(self, run_id: str) -> list[AgentTraceEvent]:
        """列出Agent追踪事件"""
        cursor = self._connection.execute(
            """
            SELECT payload FROM agent_trace_events
            WHERE run_id = ?
            ORDER BY event_id
            """,
            (run_id,),
        )
        return [AgentTraceEvent.model_validate_json(row[0]) for row in cursor.fetchall()]

    def clear_events(self, run_id: str) -> None:
        """清空Agent追踪事件"""
        self._connection.execute(
            "DELETE FROM agent_trace_events WHERE run_id = ?",
            (run_id,),
        )
        self._connection.commit()

    def close(self) -> None:
        """关闭数据库连接"""
        self._connection.close()
