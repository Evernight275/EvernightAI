from pathlib import Path

from EvernightAI.core.error.skill import SkillNotFoundError
from EvernightAI.core.protocol.skill import SkillTemplateStoreProtocol
from EvernightAI.core.schema.skill import SkillTemplateConfig
from EvernightAI.infra.sqlite import (
    SQLiteMigrationRunner,
    connect_sqlite,
    sqlite_transaction,
)


class SQLiteSkillTemplateStore(SkillTemplateStoreProtocol):
    def __init__(self, database_path: str | Path) -> None:
        self._connection = connect_sqlite(database_path)
        SQLiteMigrationRunner(database_path).run(self._connection)

    def save(self, config: SkillTemplateConfig) -> None:
        with sqlite_transaction(self._connection, immediate=True):
            self._connection.execute(
                "INSERT INTO skill_templates (name, payload) VALUES (?, ?) "
                "ON CONFLICT(name) DO UPDATE SET payload = excluded.payload",
                (config.name, config.model_dump_json()),
            )

    def list_configs(self) -> list[SkillTemplateConfig]:
        return [
            SkillTemplateConfig.model_validate_json(row[0])
            for row in self._connection.execute(
                "SELECT payload FROM skill_templates ORDER BY name"
            ).fetchall()
        ]

    def delete(self, skill_name: str) -> None:
        with sqlite_transaction(self._connection, immediate=True):
            if (
                self._connection.execute(
                    "DELETE FROM skill_templates WHERE name = ?", (skill_name,)
                ).rowcount
                == 0
            ):
                raise SkillNotFoundError(
                    f"The skill template {skill_name} is not found"
                )

    def close(self) -> None:
        self._connection.close()

    def is_ready(self) -> bool:
        try:
            return self._connection.execute("SELECT 1").fetchone() == (1,)
        except Exception:
            return False
