from pathlib import Path
from threading import RLock

from EvernightAI.core.error.base import ConflictError, NotFoundError, ValidationError
from EvernightAI.core.protocol.workspace import WorkspaceDirectoryProtocol
from EvernightAI.core.schema.workspace import (
    WorkspaceDirectory,
    WorkspaceEntry,
    WorkspaceProject,
)
from EvernightAI.infra.sqlite import (
    SQLiteConnection,
    SQLiteMigrationRunner,
    connect_sqlite,
)


class WorkspaceDirectoryStore(WorkspaceDirectoryProtocol):
    def __init__(
        self,
        root: str | Path,
        *,
        database_path: str | Path | None = None,
        protected_paths: list[str | Path] | None = None,
        browse_host_directories: bool = False,
    ) -> None:
        self._root = Path(root).resolve()
        self._browse_root = (
            (Path(self._root.anchor) if self._root.drive else Path.home().resolve())
            if browse_host_directories
            else None
        )
        self._protected = [Path(path).resolve() for path in protected_paths or []]
        self._projects: set[str] = set()
        self._database_path = database_path
        self._connection: SQLiteConnection | None = None
        self._lock = RLock()

    def _project_connection(self) -> SQLiteConnection | None:
        with self._lock:
            if self._connection is None and self._database_path is not None:
                connection = connect_sqlite(self._database_path)
                try:
                    SQLiteMigrationRunner(self._database_path).run(connection)
                except Exception:
                    connection.close()
                    raise
                self._connection = connection
            return self._connection

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()

    def list_projects(self) -> list[WorkspaceProject]:
        paths = self._registered_paths()
        return [
            WorkspaceProject(name=path.name or str(path), path=str(path))
            for path in [self._root, *sorted(paths - {self._root})]
        ]

    def _registered_paths(self) -> set[Path]:
        connection = self._project_connection()
        if connection is not None:
            return {
                Path(row[0])
                for row in connection.execute("SELECT path FROM workspace_projects")
            }
        return {Path(path) for path in self._projects}

    def _check_project(self, path: Path) -> None:
        if any(
            path.is_relative_to(protected) or protected.is_relative_to(path)
            for protected in self._protected
        ):
            raise ValidationError(
                "此目录包含服务数据或运行环境，请选择独立的项目文件夹"
            )

    def add_project(self, path: str) -> WorkspaceDirectory:
        if "\0" in path:
            raise ValidationError("请输入有效的项目路径")
        target = Path(path).expanduser()
        if not target.is_absolute():
            raise ValidationError("请输入后端主机上项目文件夹的绝对路径")
        target = target.resolve()
        self._check_project(target)
        if not target.is_dir():
            raise NotFoundError("项目文件夹不存在")
        connection = self._project_connection()
        if connection is not None:
            connection.execute(
                "INSERT OR IGNORE INTO workspace_projects (path) VALUES (?)",
                (str(target),),
            )
        else:
            self._projects.add(str(target))
        return self.browse(str(target))

    def resolve(self, path: str) -> str:
        return str(self._directory(path)[0])

    def _directory(self, path: str, *, browsing: bool = False) -> tuple[Path, Path]:
        if "\0" in path:
            raise ValidationError("请输入有效的工作目录")
        raw = Path(path)
        if ".." in raw.parts:
            raise ValidationError("不能访问工作根目录之外的路径")
        target = (self._root / raw).resolve()
        root = self._root
        if browsing and self._browse_root is not None:
            if raw == Path("."):
                target = self._browse_root
            browse_root = Path(target.anchor) if target.drive else self._browse_root
            if target.is_relative_to(browse_root):
                root = browse_root
        if not target.is_relative_to(root):
            roots = [
                candidate
                for candidate in self._registered_paths()
                if target.is_relative_to(candidate) and candidate.resolve() == candidate
            ]
            if not roots:
                raise ValidationError("请先添加此项目文件夹，再选择工作目录")
            root = max(roots, key=lambda candidate: len(candidate.parts))
            self._check_project(root)
        if not target.is_dir():
            raise NotFoundError("工作文件夹不存在")
        return target, root

    def _path(self, directory: Path, root: Path) -> str:
        return (
            directory.relative_to(self._root).as_posix()
            if root == self._root and self._browse_root is None
            else str(directory)
        )

    def browse(self, path: str) -> WorkspaceDirectory:
        directory, root = self._directory(path, browsing=True)
        entries = []
        truncated = False
        try:
            for entry in directory.iterdir():
                if len(entries) >= 500:
                    truncated = True
                    break
                if entry.is_symlink():
                    continue
                entries.append(
                    WorkspaceEntry(
                        name=entry.name,
                        path=self._path(entry, root),
                        is_directory=entry.is_dir(),
                    )
                )
        except OSError as exc:
            raise ValidationError("无法读取此工作文件夹") from exc
        entries.sort(key=lambda entry: (not entry.is_directory, entry.name.casefold()))
        requires_registration = False
        if self._browse_root is not None:
            try:
                self.resolve(str(directory))
            except ValidationError:
                requires_registration = True
        return WorkspaceDirectory(
            root=str(root),
            path=self._path(directory, root),
            parent=self._path(directory.parent, root) if directory != root else None,
            entries=entries,
            truncated=truncated,
            requires_registration=requires_registration,
        )

    def create(self, path: str, name: str) -> WorkspaceDirectory:
        if (
            not name.strip()
            or name in {".", ".."}
            or any(char in name for char in "/\\\0")
        ):
            raise ValidationError("请输入有效的文件夹名称")
        directory, root = self._directory(path, browsing=True)
        target = directory / name
        if self._browse_root is not None and any(
            target.resolve().is_relative_to(protected) for protected in self._protected
        ):
            raise ValidationError("不能在服务数据或运行环境中创建工作文件夹")
        try:
            target.mkdir()
        except FileExistsError as exc:
            raise ConflictError("此名称已存在") from exc
        except OSError as exc:
            raise ValidationError("无法创建工作文件夹") from exc
        return self.browse(self._path(target, root))
