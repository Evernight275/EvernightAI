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
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self._ensure_state_timestamps()
        self._connection.commit()

    def save_state(self, state: AgentRunState) -> None:
        """保存Agent运行状态"""
        self._connection.execute(
            """
            INSERT INTO agent_run_states (run_id, payload, created_at, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(run_id) DO UPDATE SET
                payload = excluded.payload,
                updated_at = excluded.updated_at
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

    def _ensure_state_timestamps(self) -> None:
        columns = {
            row[1]
            for row in self._connection.execute("PRAGMA table_info(agent_run_states)")
        }
        if "created_at" not in columns:
            self._connection.execute(
                "ALTER TABLE agent_run_states "
                "ADD COLUMN created_at TEXT"
            )
        if "updated_at" not in columns:
            self._connection.execute(
                "ALTER TABLE agent_run_states "
                "ADD COLUMN updated_at TEXT"
            )
        self._connection.execute(
            "UPDATE agent_run_states "
            "SET created_at = CURRENT_TIMESTAMP "
            "WHERE created_at IS NULL"
        )
        self._connection.execute(
            "UPDATE agent_run_states "
            "SET updated_at = CURRENT_TIMESTAMP "
            "WHERE updated_at IS NULL"
        )


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
                sequence INTEGER NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self._ensure_event_columns()
        self._connection.commit()

    def append_event(self, run_id: str, event: AgentTraceEvent) -> int:
        """追加Agent追踪事件"""
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            cursor = self._connection.execute(
                """
                SELECT COALESCE(MAX(sequence), 0) + 1
                FROM agent_trace_events
                WHERE run_id = ?
                """,
                (run_id,),
            )
            sequence = int(cursor.fetchone()[0])
            event.sequence = sequence
            self._connection.execute(
                """
                INSERT INTO agent_trace_events (run_id, sequence, payload)
                VALUES (?, ?, ?)
                """,
                (run_id, sequence, event.model_dump_json()),
            )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise

        return sequence

    def list_events(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
        limit: int | None = None,
    ) -> list[AgentTraceEvent]:
        """列出Agent追踪事件"""
        if limit is None:
            cursor = self._connection.execute(
                """
                SELECT sequence, payload FROM agent_trace_events
                WHERE run_id = ? AND sequence > ?
                ORDER BY sequence
                """,
                (run_id, after_sequence),
            )
        else:
            cursor = self._connection.execute(
                """
                SELECT sequence, payload FROM agent_trace_events
                WHERE run_id = ? AND sequence > ?
                ORDER BY sequence
                LIMIT ?
                """,
                (run_id, after_sequence, limit),
            )

        events: list[AgentTraceEvent] = []
        for sequence, payload in cursor.fetchall():
            event = AgentTraceEvent.model_validate_json(payload)
            event.sequence = sequence
            events.append(event)
        return events

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

    def _ensure_event_columns(self) -> None:
        columns = {
            row[1]
            for row in self._connection.execute("PRAGMA table_info(agent_trace_events)")
        }
        if "sequence" not in columns:
            self._connection.execute(
                "ALTER TABLE agent_trace_events ADD COLUMN sequence INTEGER"
            )
        if "created_at" not in columns:
            self._connection.execute(
                "ALTER TABLE agent_trace_events "
                "ADD COLUMN created_at TEXT"
            )
        next_sequence_by_run: dict[str, int] = {}
        rows = self._connection.execute(
            """
            SELECT event_id, run_id, sequence
            FROM agent_trace_events
            ORDER BY run_id, event_id
            """
        ).fetchall()
        for event_id, run_id, sequence in rows:
            next_sequence = next_sequence_by_run.get(run_id, 0) + 1
            if sequence is None:
                self._connection.execute(
                    "UPDATE agent_trace_events SET sequence = ? WHERE event_id = ?",
                    (next_sequence, event_id),
                )
            else:
                next_sequence = max(next_sequence, int(sequence))
            next_sequence_by_run[run_id] = next_sequence
        self._connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS agent_trace_events_run_sequence_idx
            ON agent_trace_events (run_id, sequence)
            """
        )
        self._connection.execute(
            "UPDATE agent_trace_events "
            "SET created_at = CURRENT_TIMESTAMP "
            "WHERE created_at IS NULL"
        )
