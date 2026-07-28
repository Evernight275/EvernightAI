from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3
from threading import RLock
from typing import Any


DEFAULT_BUSY_TIMEOUT_MS = 5_000


class SQLiteConnection(sqlite3.Connection):
    """SQLite connection serialized across runtime and TestClient threads."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.lock = RLock()

    def execute(
        self,
        sql: str,
        parameters: Any = (),
    ) -> sqlite3.Cursor:
        with self.lock:
            return super().execute(sql, parameters)

    def commit(self) -> None:
        with self.lock:
            super().commit()

    def rollback(self) -> None:
        with self.lock:
            super().rollback()

    def close(self) -> None:
        with self.lock:
            super().close()


def connect_sqlite(
    database_path: str | Path,
    *,
    busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
) -> SQLiteConnection:
    path = str(database_path)
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(
        path,
        timeout=busy_timeout_ms / 1_000,
        isolation_level=None,
        check_same_thread=False,
        factory=SQLiteConnection,
    )
    connection.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
    connection.execute("PRAGMA foreign_keys = ON")
    if path != ":memory:":
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
    return connection


@contextmanager
def sqlite_transaction(
    connection: sqlite3.Connection,
    *,
    immediate: bool = False,
) -> Iterator[None]:
    lock = connection.lock if isinstance(connection, SQLiteConnection) else RLock()
    with lock:
        connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
        try:
            yield
        except Exception:
            connection.rollback()
            raise
        else:
            connection.commit()


MigrationOperation = Callable[[sqlite3.Connection], None]


@dataclass(frozen=True)
class SQLiteMigration:
    version: int
    name: str
    operation: MigrationOperation


class SQLiteMigrationRunner:
    def __init__(
        self,
        database_path: str | Path,
        *,
        migrations: tuple[SQLiteMigration, ...] | None = None,
    ) -> None:
        self._database_path = str(database_path)
        self._migrations = migrations or DEFAULT_MIGRATIONS

    def run(self, connection: sqlite3.Connection | None = None) -> int:
        owns_connection = connection is None
        connection = connection or connect_sqlite(self._database_path)
        try:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS evernight_schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            for migration in self._migrations:
                with sqlite_transaction(connection, immediate=True):
                    applied = connection.execute(
                        "SELECT 1 FROM evernight_schema_migrations WHERE version = ?",
                        (migration.version,),
                    ).fetchone()
                    if applied is not None:
                        continue
                    migration.operation(connection)
                    connection.execute(
                        """
                        INSERT INTO evernight_schema_migrations (version, name)
                        VALUES (?, ?)
                        """,
                        (migration.version, migration.name),
                    )
            row = connection.execute(
                "SELECT COALESCE(MAX(version), 0) FROM evernight_schema_migrations"
            ).fetchone()
            return int(row[0])
        finally:
            if owns_connection:
                connection.close()


def _create_runtime_tables(connection: sqlite3.Connection) -> None:
    statements = (
        """
        CREATE TABLE IF NOT EXISTS contexts (
            context_id TEXT PRIMARY KEY,
            payload TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS memories (
            memory_id TEXT PRIMARY KEY,
            payload TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            payload TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS agent_run_states (
            run_id TEXT PRIMARY KEY,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS agent_trace_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            sequence INTEGER,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
    )
    for statement in statements:
        connection.execute(statement)


def _add_queryable_columns(connection: sqlite3.Connection) -> None:
    _ensure_column(connection, "contexts", "revision", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(connection, "contexts", "owner_id", "TEXT")

    _ensure_column(connection, "memories", "kind", "TEXT")
    _ensure_column(connection, "memories", "scope", "TEXT")
    _ensure_column(connection, "memories", "scope_id", "TEXT")
    _ensure_column(connection, "memories", "is_enabled", "INTEGER NOT NULL DEFAULT 1")
    _ensure_column(connection, "memories", "owner_id", "TEXT")

    _ensure_column(connection, "sessions", "status", "TEXT")
    _ensure_column(connection, "sessions", "provider_id", "TEXT")
    _ensure_column(connection, "sessions", "model_id", "TEXT")
    _ensure_column(connection, "sessions", "updated_at", "TEXT")
    _ensure_column(connection, "sessions", "owner_id", "TEXT")

    _ensure_column(connection, "agent_run_states", "status", "TEXT")
    _ensure_column(connection, "agent_run_states", "context_id", "TEXT")
    _ensure_column(connection, "agent_run_states", "owner_id", "TEXT")
    _ensure_column(connection, "agent_run_states", "lease_owner", "TEXT")
    _ensure_column(connection, "agent_run_states", "lease_expires_at", "TEXT")
    _ensure_column(connection, "agent_run_states", "heartbeat_at", "TEXT")
    _ensure_column(
        connection,
        "agent_run_states",
        "lease_generation",
        "INTEGER NOT NULL DEFAULT 0",
    )
    _ensure_column(connection, "agent_run_states", "created_at", "TEXT")
    _ensure_column(connection, "agent_run_states", "updated_at", "TEXT")

    _ensure_column(connection, "agent_trace_events", "sequence", "INTEGER")
    _ensure_column(connection, "agent_trace_events", "created_at", "TEXT")

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS provider_configs (
            provider_id TEXT PRIMARY KEY,
            provider_type TEXT NOT NULL,
            is_enabled INTEGER NOT NULL,
            secret_ref TEXT,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    _backfill_queryable_columns(connection)
    _backfill_trace_sequences(connection)

    indexes = (
        "CREATE INDEX IF NOT EXISTS idx_contexts_owner_id ON contexts(owner_id, context_id)",
        "CREATE INDEX IF NOT EXISTS idx_memories_scope ON memories(scope, scope_id, memory_id)",
        "CREATE INDEX IF NOT EXISTS idx_memories_owner_id ON memories(owner_id, memory_id)",
        "CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status, session_id)",
        "CREATE INDEX IF NOT EXISTS idx_sessions_updated_at ON sessions(updated_at, session_id)",
        "CREATE INDEX IF NOT EXISTS idx_sessions_owner_id ON sessions(owner_id, session_id)",
        "CREATE INDEX IF NOT EXISTS idx_agent_runs_status ON agent_run_states(status, run_id)",
        "CREATE INDEX IF NOT EXISTS idx_agent_runs_context ON agent_run_states(context_id, run_id)",
        "CREATE INDEX IF NOT EXISTS idx_agent_runs_owner_id ON agent_run_states(owner_id, run_id)",
        "CREATE INDEX IF NOT EXISTS idx_agent_runs_lease ON agent_run_states(lease_expires_at)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_trace_run_sequence ON agent_trace_events(run_id, sequence)",
        "CREATE INDEX IF NOT EXISTS idx_agent_trace_created_at ON agent_trace_events(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_provider_configs_enabled ON provider_configs(is_enabled, provider_id)",
    )
    for statement in indexes:
        connection.execute(statement)


def _ensure_column(
    connection: sqlite3.Connection,
    table: str,
    column: str,
    declaration: str,
) -> None:
    columns = {
        str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")
    }
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")


def _backfill_queryable_columns(connection: sqlite3.Connection) -> None:
    mappings: dict[str, tuple[str, dict[str, str]]] = {
        "contexts": ("context_id", {"revision": "revision", "owner_id": "owner_id"}),
        "memories": (
            "memory_id",
            {
                "kind": "kind",
                "scope": "scope",
                "scope_id": "scope_id",
                "is_enabled": "is_enabled",
                "owner_id": "owner_id",
                "relevance": "relevance",
                "confidence": "confidence",
                "expires_at": "expires_at",
                "updated_at": "updated_at",
            },
        ),
        "sessions": (
            "session_id",
            {
                "status": "status",
                "provider_id": "provider_id",
                "model_id": "model_id",
                "updated_at": "updated_at",
                "owner_id": "owner_id",
            },
        ),
        "agent_run_states": (
            "run_id",
            {
                "status": "status",
                "context_id": "request.context_id",
                "owner_id": "owner_id",
            },
        ),
    }
    for table, (identity_column, columns) in mappings.items():
        existing_columns = {
            str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")
        }
        columns = {
            column: path
            for column, path in columns.items()
            if column in existing_columns
        }
        if not columns:
            continue
        rows = connection.execute(
            f"SELECT {identity_column}, payload FROM {table}"
        ).fetchall()
        for identity, raw_payload in rows:
            try:
                payload = json.loads(raw_payload)
            except (TypeError, json.JSONDecodeError):
                continue
            values = [
                _backfill_value(table, column, _nested_value(payload, path))
                for column, path in columns.items()
            ]
            assignments = ", ".join(f"{column} = ?" for column in columns)
            connection.execute(
                f"UPDATE {table} SET {assignments} WHERE {identity_column} = ?",
                (*values, identity),
            )

    connection.execute(
        "UPDATE agent_run_states SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"
    )
    connection.execute(
        "UPDATE agent_run_states SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL"
    )
    connection.execute(
        "UPDATE agent_trace_events SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"
    )


def _nested_value(payload: object, path: str) -> object:
    value = payload
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    if isinstance(value, bool):
        return int(value)
    return value


def _backfill_value(table: str, column: str, value: object) -> object:
    if value is not None:
        return value
    if table == "contexts" and column == "revision":
        return 0
    if table == "memories" and column == "is_enabled":
        return 1
    if table == "memories" and column == "relevance":
        return 0.0
    if table == "memories" and column == "confidence":
        return 1.0
    return None


def _backfill_trace_sequences(connection: sqlite3.Connection) -> None:
    next_sequence_by_run: dict[str, int] = {}
    rows = connection.execute(
        """
        SELECT event_id, run_id, sequence
        FROM agent_trace_events
        ORDER BY run_id, event_id
        """
    ).fetchall()
    for event_id, run_id, sequence in rows:
        next_sequence = next_sequence_by_run.get(str(run_id), 0) + 1
        if sequence is None:
            connection.execute(
                "UPDATE agent_trace_events SET sequence = ? WHERE event_id = ?",
                (next_sequence, event_id),
            )
        else:
            next_sequence = max(next_sequence, int(sequence))
        next_sequence_by_run[str(run_id)] = next_sequence


def _add_memory_policy_columns(connection: sqlite3.Connection) -> None:
    _ensure_column(connection, "memories", "relevance", "REAL NOT NULL DEFAULT 0")
    _ensure_column(connection, "memories", "confidence", "REAL NOT NULL DEFAULT 1")
    _ensure_column(connection, "memories", "expires_at", "TEXT")
    _ensure_column(connection, "memories", "updated_at", "TEXT")
    _backfill_queryable_columns(connection)
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_memories_expiry ON memories(expires_at, memory_id)"
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_memories_ranking
        ON memories(scope, scope_id, relevance DESC, confidence DESC, memory_id)
        """
    )


def _add_agent_tool_execution_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_tool_executions (
            run_id TEXT NOT NULL,
            tool_call_id TEXT NOT NULL,
            attempt INTEGER NOT NULL,
            owner_id TEXT,
            status TEXT NOT NULL,
            replay_policy TEXT NOT NULL,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (run_id, tool_call_id, attempt),
            FOREIGN KEY (run_id) REFERENCES agent_run_states(run_id) ON DELETE CASCADE
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_agent_tool_executions_run_status
        ON agent_tool_executions(run_id, status, tool_call_id, attempt)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_agent_tool_executions_owner
        ON agent_tool_executions(owner_id, run_id, tool_call_id, attempt)
        """
    )


DEFAULT_MIGRATIONS = (
    SQLiteMigration(1, "create runtime tables", _create_runtime_tables),
    SQLiteMigration(2, "add queryable columns and indexes", _add_queryable_columns),
    SQLiteMigration(3, "add memory policy columns", _add_memory_policy_columns),
    SQLiteMigration(4, "add agent tool execution table", _add_agent_tool_execution_table),
)
