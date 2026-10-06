from pathlib import Path
import sqlite3

from EvernightAI.core.domain.file import validate_file_content
from EvernightAI.core.error.base import ConflictError, NotFoundError
from EvernightAI.core.protocol.file import FileArtifactStoreProtocol
from EvernightAI.core.schema.auth import PrincipalScope
from EvernightAI.core.schema.file import FileArtifact
from EvernightAI.infra.sqlite import SQLiteMigrationRunner, connect_sqlite


class SQLiteFileArtifactStore(FileArtifactStoreProtocol):
    def __init__(self, database_path: str | Path) -> None:
        self._connection = connect_sqlite(database_path)
        SQLiteMigrationRunner(database_path).run(self._connection)

    def save(self, artifact: FileArtifact, content: bytes) -> None:
        validate_file_content(artifact, content)
        try:
            self._connection.execute(
                "INSERT INTO file_artifacts (artifact_id, owner_id, payload, content) VALUES (?, ?, ?, ?)",
                (
                    artifact.artifact_id,
                    artifact.owner_id,
                    artifact.model_dump_json(),
                    content,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ConflictError("展示文件已存在") from exc

    def _get(self, artifact_id: str, scope: PrincipalScope | None, column: str):
        where = "artifact_id = ?"
        values: tuple[object, ...] = (artifact_id,)
        if scope is not None and scope.owner_id is not None:
            where += " AND owner_id = ?"
            values += (scope.owner_id,)
        row = self._connection.execute(
            f"SELECT {column} FROM file_artifacts WHERE {where}", values
        ).fetchone()
        if row is None:
            raise NotFoundError("展示文件不存在")
        return row[0]

    def get(
        self, artifact_id: str, *, principal_scope: PrincipalScope | None = None
    ) -> FileArtifact:
        return FileArtifact.model_validate_json(
            self._get(artifact_id, principal_scope, "payload")
        )

    def read(
        self, artifact_id: str, *, principal_scope: PrincipalScope | None = None
    ) -> bytes:
        return bytes(self._get(artifact_id, principal_scope, "content"))

    def is_ready(self) -> bool:
        try:
            return self._connection.execute("SELECT 1").fetchone() == (1,)
        except Exception:
            return False

    def close(self) -> None:
        self._connection.close()
