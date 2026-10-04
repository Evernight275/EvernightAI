from datetime import datetime, timezone
from pathlib import Path

from EvernightAI.core.domain.image_task import (
    MAX_ACTIVE_IMAGE_TASKS,
    interrupted,
    same_submission,
)
from EvernightAI.core.error.image import (
    ImageTaskConflictError,
    ImageTaskLimitError,
    ImageTaskNotFoundError,
)
from EvernightAI.core.protocol.image import ImageTaskStoreProtocol
from EvernightAI.core.schema.auth import PrincipalScope
from EvernightAI.core.schema.image import ImageHistoryCursor
from EvernightAI.core.schema.image_task import ImageTask, ImageTaskSummary
from EvernightAI.infra.sqlite import (
    SQLiteMigrationRunner,
    connect_sqlite,
    sqlite_transaction,
)


class SQLiteImageTaskStore(ImageTaskStoreProtocol):
    def __init__(self, database_path: str | Path) -> None:
        self._connection = connect_sqlite(database_path)
        SQLiteMigrationRunner(database_path).run(self._connection)

    def has_active(self) -> bool:
        return (
            self._connection.execute(
                "SELECT 1 FROM image_tasks WHERE status IN ('queued', 'running') LIMIT 1"
            ).fetchone()
            is not None
        )

    def delete_for_record(self, record_id: str) -> None:
        with sqlite_transaction(self._connection, immediate=True):
            self._connection.execute(
                "DELETE FROM image_tasks WHERE task_id = ?", (record_id,)
            )

    def create(self, task: ImageTask) -> bool:
        with sqlite_transaction(self._connection, immediate=True):
            row = self._connection.execute(
                "SELECT payload FROM image_tasks WHERE task_id = ?", (task.task_id,)
            ).fetchone()
            if row is not None:
                previous = ImageTask.model_validate_json(row[0])
                if previous.owner_id != task.owner_id:
                    raise ImageTaskNotFoundError("Image task not found")
                if not same_submission(previous, task):
                    raise ImageTaskConflictError(
                        "Image task ID already belongs to another request"
                    )
                return False
            count = self._connection.execute(
                "SELECT COUNT(*) FROM image_tasks WHERE owner_id IS ? AND status IN ('queued', 'running')",
                (task.owner_id,),
            ).fetchone()[0]
            if count >= MAX_ACTIVE_IMAGE_TASKS:
                raise ImageTaskLimitError("最多同时保留 10 个待完成的图片任务")
            self._connection.execute(
                "INSERT INTO image_tasks (task_id, owner_id, session_id, status, created_at, worker_id, lease_expires_at, summary, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    task.task_id,
                    task.owner_id,
                    task.session_id,
                    task.status,
                    task.created_at.isoformat(),
                    None,
                    None,
                    task.summary().model_dump_json(),
                    task.model_dump_json(),
                ),
            )
        return True

    def get(
        self, task_id: str, *, principal_scope: PrincipalScope | None = None
    ) -> ImageTask:
        row = self._connection.execute(
            "SELECT payload, worker_id, lease_expires_at FROM image_tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if row is None:
            raise ImageTaskNotFoundError("Image task not found")
        task = ImageTask.model_validate_json(row[0])
        if principal_scope is not None and not principal_scope.permits(task.owner_id):
            raise ImageTaskNotFoundError("Image task not found")
        return task.model_copy(
            update={
                "worker_id": row[1],
                "lease_expires_at": datetime.fromisoformat(row[2]) if row[2] else None,
            }
        )

    def get_summary(
        self, task_id: str, *, principal_scope: PrincipalScope | None = None
    ) -> ImageTaskSummary:
        row = self._connection.execute(
            "SELECT owner_id, summary FROM image_tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
        if row is None or (
            principal_scope is not None and not principal_scope.permits(row[0])
        ):
            raise ImageTaskNotFoundError("Image task not found")
        return ImageTaskSummary.model_validate_json(row[1])

    def list_tasks(
        self,
        *,
        limit: int,
        cursor: ImageHistoryCursor | None = None,
        session_id: str | None = None,
        principal_scope: PrincipalScope | None = None,
    ) -> list[ImageTaskSummary]:
        where: list[str] = []
        values: list[object] = []
        if principal_scope is not None and principal_scope.owner_id is not None:
            where.append("owner_id = ?")
            values.append(principal_scope.owner_id)
        if session_id is not None:
            where.append("session_id = ?")
            values.append(session_id)
        if cursor is not None:
            where.append("(created_at, task_id) < (?, ?)")
            values.extend((cursor.created_at.isoformat(), cursor.record_id))
        sql = "SELECT summary FROM image_tasks"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at DESC, task_id DESC LIMIT ?"
        values.append(limit)
        return [
            ImageTaskSummary.model_validate_json(row[0])
            for row in self._connection.execute(sql, values).fetchall()
        ]

    def _update(self, task: ImageTask, worker_id: str | None) -> bool:
        result = self._connection.execute(
            "UPDATE image_tasks SET status = ?, worker_id = ?, lease_expires_at = ?, summary = ?, payload = ? WHERE task_id = ? AND status = 'running' AND worker_id IS ?",
            (
                task.status,
                task.worker_id,
                task.lease_expires_at.isoformat() if task.lease_expires_at else None,
                task.summary().model_dump_json(),
                task.model_dump_json(),
                task.task_id,
                worker_id,
            ),
        )
        return result.rowcount == 1

    def claim(self, worker_id: str, lease_expires_at: datetime) -> ImageTask | None:
        if (
            self._connection.execute(
                "SELECT 1 FROM image_tasks WHERE status = 'queued' LIMIT 1"
            ).fetchone()
            is None
        ):
            return None
        with sqlite_transaction(self._connection, immediate=True):
            row = self._connection.execute(
                "SELECT payload FROM image_tasks WHERE status = 'queued' ORDER BY created_at, task_id LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            task = ImageTask.model_validate_json(row[0]).model_copy(
                update={
                    "status": "running",
                    "worker_id": worker_id,
                    "lease_expires_at": lease_expires_at,
                    "updated_at": datetime.now(timezone.utc),
                }
            )
            self._connection.execute(
                "UPDATE image_tasks SET status = ?, worker_id = ?, lease_expires_at = ?, summary = ?, payload = ? WHERE task_id = ? AND status = 'queued'",
                (
                    task.status,
                    worker_id,
                    lease_expires_at.isoformat(),
                    task.summary().model_dump_json(),
                    task.model_dump_json(),
                    task.task_id,
                ),
            )
            return task

    def renew(self, task_id: str, worker_id: str, lease_expires_at: datetime) -> bool:
        with sqlite_transaction(self._connection, immediate=True):
            result = self._connection.execute(
                "UPDATE image_tasks SET lease_expires_at = ? WHERE task_id = ? AND status = 'running' AND worker_id = ?",
                (lease_expires_at.isoformat(), task_id, worker_id),
            )
            return result.rowcount == 1

    def finish(self, task: ImageTask, worker_id: str) -> bool:
        task = task.model_copy(update={"worker_id": None, "lease_expires_at": None})
        with sqlite_transaction(self._connection, immediate=True):
            return self._update(task, worker_id)

    def recover_expired(self, now: datetime) -> None:
        rows = self._connection.execute(
            "SELECT payload FROM image_tasks WHERE status = 'running' AND (lease_expires_at IS NULL OR lease_expires_at <= ?)",
            (now.isoformat(),),
        ).fetchall()
        if not rows:
            return
        with sqlite_transaction(self._connection, immediate=True):
            for row in rows:
                task = ImageTask.model_validate_json(row[0])
                current = self.get(task.task_id)
                if current.status == "running" and (
                    current.lease_expires_at is None or current.lease_expires_at <= now
                ):
                    self._update(interrupted(current), current.worker_id)

    def close(self) -> None:
        self._connection.close()

    def is_ready(self) -> bool:
        try:
            return self._connection.execute("SELECT 1").fetchone() == (1,)
        except Exception:
            return False
