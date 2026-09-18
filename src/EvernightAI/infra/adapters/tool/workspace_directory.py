from pathlib import Path

from EvernightAI.core.error.base import ConflictError, NotFoundError, ValidationError
from EvernightAI.core.protocol.workspace import WorkspaceDirectoryProtocol
from EvernightAI.core.schema.workspace import WorkspaceDirectory, WorkspaceEntry


class WorkspaceDirectoryStore(WorkspaceDirectoryProtocol):
    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).resolve()

    def _directory(self, path: str) -> Path:
        relative = Path(path)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValidationError("工作目录必须位于已配置的根目录内")
        target = (self._root / relative).resolve()
        if not target.is_relative_to(self._root):
            raise ValidationError("不能访问工作根目录之外的路径")
        if not target.is_dir():
            raise NotFoundError("工作文件夹不存在")
        return target

    def browse(self, path: str) -> WorkspaceDirectory:
        directory = self._directory(path)
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
                        path=entry.relative_to(self._root).as_posix(),
                        is_directory=entry.is_dir(),
                    )
                )
        except OSError as exc:
            raise ValidationError("无法读取此工作文件夹") from exc
        entries.sort(key=lambda entry: (not entry.is_directory, entry.name.casefold()))
        return WorkspaceDirectory(
            root=str(self._root),
            path=directory.relative_to(self._root).as_posix(),
            entries=entries,
            truncated=truncated,
        )

    def create(self, path: str, name: str) -> WorkspaceDirectory:
        if (
            not name.strip()
            or name in {".", ".."}
            or any(char in name for char in "/\\\0")
        ):
            raise ValidationError("请输入有效的文件夹名称")
        target = self._directory(path) / name
        try:
            target.mkdir()
        except FileExistsError as exc:
            raise ConflictError("此名称已存在") from exc
        except OSError as exc:
            raise ValidationError("无法创建工作文件夹") from exc
        return self.browse(target.relative_to(self._root).as_posix())
