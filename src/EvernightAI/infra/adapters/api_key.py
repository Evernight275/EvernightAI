from datetime import datetime
from pathlib import Path

from EvernightAI.core.protocol.api_key import ApiKeyRegisterProtocol
from EvernightAI.core.schema.api_key import ApiKeyInfo
from EvernightAI.infra.sqlite import (
    SQLiteMigrationRunner,
    connect_sqlite,
    sqlite_transaction,
)


class SQLiteApiKeyRegister(ApiKeyRegisterProtocol):
    def __init__(self, database_path: str | Path) -> None:
        self._connection = connect_sqlite(database_path)
        SQLiteMigrationRunner(database_path).run(self._connection)

    def create(self, info: ApiKeyInfo, digest: str) -> None:
        with sqlite_transaction(self._connection, immediate=True):
            self._connection.execute(
                "INSERT INTO auth_api_keys (key_id, owner_id, digest, payload) VALUES (?, ?, ?, ?)",
                (info.key_id, info.owner_id, digest, info.model_dump_json()),
            )

    def get_by_digest(self, digest: str) -> ApiKeyInfo | None:
        row = self._connection.execute(
            "SELECT payload FROM auth_api_keys WHERE digest = ?", (digest,)
        ).fetchone()
        return ApiKeyInfo.model_validate_json(row[0]) if row is not None else None

    def list_keys(self, owner_id: str) -> list[ApiKeyInfo]:
        rows = self._connection.execute(
            "SELECT payload FROM auth_api_keys WHERE owner_id = ? ORDER BY rowid DESC",
            (owner_id,),
        ).fetchall()
        return [ApiKeyInfo.model_validate_json(row[0]) for row in rows]

    def revoke(self, owner_id: str, key_id: str, revoked_at: datetime) -> bool:
        with sqlite_transaction(self._connection, immediate=True):
            row = self._connection.execute(
                "SELECT payload FROM auth_api_keys WHERE owner_id = ? AND key_id = ?",
                (owner_id, key_id),
            ).fetchone()
            if row is None:
                return False
            info = ApiKeyInfo.model_validate_json(row[0])
            if info.revoked_at is None:
                info.revoked_at = revoked_at
                self._connection.execute(
                    "UPDATE auth_api_keys SET payload = ? WHERE owner_id = ? AND key_id = ?",
                    (info.model_dump_json(), owner_id, key_id),
                )
        return True

    def close(self) -> None:
        self._connection.close()
