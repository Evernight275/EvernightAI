from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import sys
import os

from EvernightAI.core.error.sandbox import SandboxConfigurationError


def default_python_runtime_roots() -> list[Path]:
    base = Path(sys.base_prefix).resolve()
    uv_root = Path.home() / ".local/share/uv/python"
    if base.parent.name == "python" and base.parent.parent.name == "uv":
        uv_root = base.parent
    return [base, uv_root.resolve()]


@dataclass(frozen=True)
class ProjectExecutionEnvironment:
    root: Path
    cwd: Path
    virtualenv: Path | None
    python_runtime: Path | None

    def sandbox_path(self, path: Path) -> str:
        relative = path.relative_to(self.root)
        return (PurePosixPath("/workspace") / PurePosixPath(*relative.parts)).as_posix()


def resolve_project_environment(
    root: Path, cwd: str | None
) -> ProjectExecutionEnvironment:
    sandbox_cwd = PurePosixPath(cwd or "/workspace")
    try:
        relative = sandbox_cwd.relative_to("/workspace")
    except ValueError as exc:
        raise SandboxConfigurationError(
            "Working directory must stay inside /workspace"
        ) from exc
    host_cwd = (root / Path(*relative.parts)).resolve()
    if not host_cwd.is_relative_to(root):
        raise SandboxConfigurationError(
            "Working directory must stay inside the selected project"
        )
    for directory in [host_cwd, *host_cwd.parents]:
        if not directory.is_relative_to(root):
            break
        candidate = directory / ".venv"
        if not candidate.exists() and not candidate.is_symlink():
            continue
        virtualenv = candidate.resolve()
        if not virtualenv.is_relative_to(root):
            raise SandboxConfigurationError(
                "Project .venv must stay inside the selected project"
            )
        config_path = virtualenv / "pyvenv.cfg"
        if not config_path.is_file():
            raise SandboxConfigurationError("Project .venv is missing pyvenv.cfg")
        if not config_path.resolve().is_relative_to(root):
            raise SandboxConfigurationError(
                "Project pyvenv.cfg must stay inside the selected project"
            )
        interpreter = virtualenv / "bin/python"
        if not interpreter.is_file():
            raise SandboxConfigurationError(
                "Project .venv Python interpreter is missing"
            )
        target = interpreter.resolve()
        if target.parent.name != "bin":
            raise SandboxConfigurationError(
                "Project Python interpreter must belong to a Python installation"
            )
        runtime = target.parent.parent
        try:
            if config_path.stat().st_size > 65536:
                raise SandboxConfigurationError("Project pyvenv.cfg is too large")
            for line in config_path.read_text(encoding="utf-8").splitlines():
                key, separator, value = line.partition("=")
                if separator and key.strip() == "home":
                    home = Path(value.strip())
                    if not home.is_absolute() or not home.is_dir():
                        raise SandboxConfigurationError(
                            "Project Python home must be an existing absolute directory"
                        )
                    runtime = Path(os.path.abspath(home)).parent
                    break
        except (OSError, UnicodeError) as exc:
            raise SandboxConfigurationError(
                "Could not read project pyvenv.cfg"
            ) from exc
        if not target.is_relative_to(virtualenv) and not target.is_relative_to(
            runtime.resolve()
        ):
            raise SandboxConfigurationError(
                "Project interpreter does not match pyvenv.cfg home"
            )
        return ProjectExecutionEnvironment(root, host_cwd, virtualenv, runtime)
    return ProjectExecutionEnvironment(root, host_cwd, None, None)
