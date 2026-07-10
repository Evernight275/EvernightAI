from pathlib import Path

from EvernightAI.core.error.provider import ProviderNotFoundError
from EvernightAI.core.protocol.provider import ProviderConfigStoreProtocol
from EvernightAI.core.schema.provider import ProviderConfig
from EvernightAI.infra.sqlite import (
    SQLiteMigrationRunner,
    connect_sqlite,
    sqlite_transaction,
)


class SQLiteProviderConfigStore(ProviderConfigStoreProtocol):
    def __init__(self, database_path: str | Path) -> None:
        self._database_path = str(database_path)
        self._connection = connect_sqlite(self._database_path)
        SQLiteMigrationRunner(self._database_path).run(self._connection)

    def save(self, provider: ProviderConfig) -> None:
        sanitized = provider.model_copy(update={"api_key": None})
        with sqlite_transaction(self._connection, immediate=True):
            self._connection.execute(
                """
                INSERT INTO provider_configs (
                    provider_id, provider_type, is_enabled, secret_ref, payload
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(provider_id) DO UPDATE SET
                    provider_type = excluded.provider_type,
                    is_enabled = excluded.is_enabled,
                    secret_ref = excluded.secret_ref,
                    payload = excluded.payload,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    sanitized.provider_id,
                    sanitized.type.value,
                    int(sanitized.is_enabled),
                    sanitized.api_key_secret_ref,
                    sanitized.model_dump_json(exclude={"api_key"}),
                ),
            )

    def get(self, provider_id: str) -> ProviderConfig:
        row = self._connection.execute(
            "SELECT payload FROM provider_configs WHERE provider_id = ?",
            (provider_id,),
        ).fetchone()
        if row is None:
            raise ProviderNotFoundError(
                f"The provider configuration {provider_id} is not found"
            )
        return ProviderConfig.model_validate_json(row[0])

    def list_configs(self, *, enabled_only: bool = False) -> list[ProviderConfig]:
        sql = "SELECT payload FROM provider_configs"
        if enabled_only:
            sql += " WHERE is_enabled = 1"
        sql += " ORDER BY provider_id"
        rows = self._connection.execute(sql).fetchall()
        return [ProviderConfig.model_validate_json(row[0]) for row in rows]

    def delete(self, provider_id: str) -> None:
        with sqlite_transaction(self._connection, immediate=True):
            cursor = self._connection.execute(
                "DELETE FROM provider_configs WHERE provider_id = ?",
                (provider_id,),
            )
            if cursor.rowcount == 0:
                raise ProviderNotFoundError(
                    f"The provider configuration {provider_id} is not registered"
                )

    def close(self) -> None:
        self._connection.close()

    def is_ready(self) -> bool:
        try:
            return self._connection.execute("SELECT 1").fetchone() == (1,)
        except Exception:
            return False
