from pathlib import Path

from EvernightAI.core.error.image import (
    ImageRecordConflictError,
    ImageRecordNotFoundError,
)
from EvernightAI.core.protocol.image import ImageGenerationStoreProtocol
from EvernightAI.core.schema.auth import PrincipalScope
from EvernightAI.core.schema.image import (
    ImageGenerationRecord,
    ImageGenerationSummary,
    ImageHistoryCursor,
)
from EvernightAI.infra.sqlite import (
    SQLiteMigrationRunner,
    connect_sqlite,
    sqlite_transaction,
)


class SQLiteImageGenerationStore(ImageGenerationStoreProtocol):
    def __init__(self, database_path: str | Path) -> None:
        self._connection = connect_sqlite(database_path)
        SQLiteMigrationRunner(database_path).run(self._connection)

    def save(self, record: ImageGenerationRecord) -> None:
        with sqlite_transaction(self._connection, immediate=True):
            previous = self._connection.execute(
                "SELECT owner_id FROM image_records WHERE record_id = ?",
                (record.record_id,),
            ).fetchone()
            if previous is not None and previous[0] != record.owner_id:
                raise ImageRecordConflictError("Image record ownership cannot change")
            self._connection.execute(
                """
                INSERT INTO image_records (record_id, owner_id, created_at, summary, payload)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(record_id) DO UPDATE SET summary = excluded.summary, payload = excluded.payload
            """,
                (
                    record.record_id,
                    record.owner_id,
                    record.created_at.isoformat(),
                    record.summary().model_dump_json(),
                    record.model_dump_json(),
                ),
            )

    def update(self, record: ImageGenerationRecord) -> None:
        with sqlite_transaction(self._connection, immediate=True):
            result = self._connection.execute(
                "UPDATE image_records SET summary = ?, payload = ? WHERE record_id = ? AND owner_id IS ?",
                (
                    record.summary().model_dump_json(),
                    record.model_dump_json(),
                    record.record_id,
                    record.owner_id,
                ),
            )
            if result.rowcount == 0:
                raise ImageRecordNotFoundError("Image record not found")

    def _identity(
        self, record_id: str, scope: PrincipalScope | None
    ) -> tuple[str, tuple[object, ...]]:
        if scope is None or scope.owner_id is None:
            return "record_id = ?", (record_id,)
        return "record_id = ? AND owner_id = ?", (record_id, scope.owner_id)

    def get(
        self, record_id: str, *, principal_scope: PrincipalScope | None = None
    ) -> ImageGenerationRecord:
        where, values = self._identity(record_id, principal_scope)
        row = self._connection.execute(
            f"SELECT payload FROM image_records WHERE {where}", values
        ).fetchone()
        if row is None:
            raise ImageRecordNotFoundError("Image record not found")
        return ImageGenerationRecord.model_validate_json(row[0])

    def list_records(
        self,
        *,
        limit: int,
        cursor: ImageHistoryCursor | None = None,
        principal_scope: PrincipalScope | None = None,
    ) -> list[ImageGenerationSummary]:
        where: list[str] = []
        values: list[object] = []
        if principal_scope is not None and principal_scope.owner_id is not None:
            where.append("owner_id = ?")
            values.append(principal_scope.owner_id)
        if cursor is not None:
            where.append("(created_at, record_id) < (?, ?)")
            values.extend((cursor.created_at.isoformat(), cursor.record_id))
        sql = "SELECT summary FROM image_records"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at DESC, record_id DESC LIMIT ?"
        values.append(limit)
        return [
            ImageGenerationSummary.model_validate_json(row[0])
            for row in self._connection.execute(sql, values).fetchall()
        ]

    def delete(
        self, record_id: str, *, principal_scope: PrincipalScope | None = None
    ) -> None:
        where, values = self._identity(record_id, principal_scope)
        with sqlite_transaction(self._connection, immediate=True):
            result = self._connection.execute(
                f"DELETE FROM image_records WHERE {where}", values
            )
            if result.rowcount == 0:
                raise ImageRecordNotFoundError("Image record not found")

    def is_ready(self) -> bool:
        try:
            return self._connection.execute("SELECT 1").fetchone() == (1,)
        except Exception:
            return False

    def close(self) -> None:
        self._connection.close()
