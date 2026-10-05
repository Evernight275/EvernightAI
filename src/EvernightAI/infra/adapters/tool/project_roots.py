from pathlib import Path

from EvernightAI.core.error.tool import ToolConfigurationError, ToolInputError
from EvernightAI.core.error.base import NotFoundError, ValidationError
from EvernightAI.core.protocol.workspace import WorkspaceDirectoryProtocol
from EvernightAI.infra.adapters.tool.workspace_directory import WorkspaceDirectoryStore


class ProjectRootResolver:
    def __init__(
        self,
        *,
        default_root: str | Path,
        project_directories: dict[str, str | Path] | None = None,
        workspace_directories: WorkspaceDirectoryProtocol | None = None,
    ) -> None:
        self._default_root = Path(default_root).resolve()
        self._workspaces = workspace_directories or WorkspaceDirectoryStore(
            self._default_root
        )
        self._project_roots = {
            project: self._resolve_project_directory(project, directory)
            for project, directory in (project_directories or {}).items()
        }

    @property
    def default_root(self) -> Path:
        return self._default_root

    @property
    def project_names(self) -> list[str]:
        return sorted(self._project_roots)

    def resolve(
        self,
        project: object,
        *,
        require_configured: bool,
        working_directory: object = None,
    ) -> tuple[str | None, Path]:
        if working_directory is not None:
            if not isinstance(working_directory, str) or not working_directory:
                raise ToolInputError("工作目录必须是有效路径")
            if project is not None:
                raise ToolInputError("已选择工作文件夹，不能同时指定其他项目")
            try:
                return None, Path(self._workspaces.resolve(working_directory))
            except (NotFoundError, ValidationError) as exc:
                raise ToolInputError(str(exc)) from exc
        if project is None:
            return None, self._default_root
        if not isinstance(project, str) or not project:
            raise ToolInputError("The project name must be a non-empty string")

        root = self._project_roots.get(project)
        if root is not None:
            return project, root
        if require_configured:
            raise ToolInputError(f"The project {project} is not configured")
        return project, self._default_root

    def _resolve_project_directory(self, project: str, directory: str | Path) -> Path:
        path = Path(directory)
        if not path.is_absolute():
            raise ToolConfigurationError(
                f"The project directory for {project} must be absolute"
            )
        resolved = path.resolve()
        if not resolved.is_dir():
            raise ToolConfigurationError(
                f"The project directory for {project} does not exist"
            )
        return resolved
