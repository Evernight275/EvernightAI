import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

import pytest

from EvernightAI.core.error.sandbox import SandboxConfigurationError
from EvernightAI.infra.adapters.sandbox.bubblewrap_policy import BubblewrapRuntimePolicy
from tests.test_sandbox_runtime import executor, request


pytestmark = [
    pytest.mark.sandbox,
    pytest.mark.skipif(
        os.name != "posix" or shutil.which("bwrap") is None,
        reason="Linux Bubblewrap is required for project environment tests",
    ),
]


@pytest.fixture
def python311_project(tmp_path):
    candidates = [Path(path) for path in [shutil.which("python3.11")] if path]
    candidates.extend(
        sorted(
            (Path.home() / ".local/share/uv/python").glob(
                "cpython-3.11*/bin/python3.11"
            )
        )
    )
    interpreter = next((path for path in candidates if path.is_file()), None)
    if interpreter is None:
        pytest.skip(
            "An installed Python 3.11 is required; no interpreter is downloaded"
        )
    root = tmp_path / "project"
    root.mkdir()
    subprocess.run(
        [str(interpreter), "-m", "venv", "--without-pip", str(root / ".venv")],
        check=True,
        capture_output=True,
    )
    site = next((root / ".venv/lib").glob("python*/site-packages"))
    (site / "only_project_dependency.py").write_text("VALUE = 'project dependency'\n")
    console = root / ".venv/bin/project-probe"
    console.write_text(
        f"#!{root / '.venv/bin/python'}\nimport sys, only_project_dependency\nprint(sys.version.split()[0])\nprint(only_project_dependency.VALUE)\n"
    )
    console.chmod(0o700)
    return root


@pytest.mark.asyncio
@pytest.mark.parametrize("form", ["array", "shell", "absolute", "path"])
async def test_project_python_version_and_dependencies_are_preserved(
    python311_project, form
):
    root = python311_project
    script = (
        "import sys, os, pathlib, only_project_dependency; "
        "print(sys.version.split()[0]); print(only_project_dependency.VALUE); "
        "print(os.environ['VIRTUAL_ENV']); "
        f"print(pathlib.Path({str(Path(sys.prefix) / 'pyvenv.cfg')!r}).exists())"
    )
    command = {
        "array": [".venv/bin/python", "-c", script],
        "shell": ["bash", "-lc", f".venv/bin/python -c {shlex.quote(script)}"],
        "absolute": [str(root / ".venv/bin/python"), "-c", script],
        "path": ["python", "-c", script],
    }[form]
    result = await executor(root).execute(request(root, command))
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[0].startswith("3.11.")
    assert lines[1:] == ["project dependency", "/workspace/.venv", "False"]


@pytest.mark.asyncio
async def test_host_shebangs_work_without_overriding_console_scripts(python311_project):
    root = python311_project
    for command in [
        ["project-probe"],
        [".venv/bin/project-probe"],
        ["bash", "-lc", ".venv/bin/project-probe"],
    ]:
        result = await executor(root).execute(request(root, command))
        assert result.returncode == 0, result.stderr
        assert result.stdout.splitlines()[0].startswith("3.11.")
        assert result.stdout.splitlines()[1] == "project dependency"


@pytest.mark.asyncio
async def test_python_installation_aliases_remain_available_and_readonly(
    python311_project, tmp_path
):
    root = python311_project
    interpreter = (root / ".venv/bin/python").resolve()
    aliases = tmp_path / "approved-runtimes"
    aliases.mkdir()
    alias = aliases / "python311"
    alias.symlink_to(interpreter.parent.parent, target_is_directory=True)
    config = root / ".venv/pyvenv.cfg"
    config.write_text(f"home = {alias / 'bin'}\ninclude-system-site-packages = false\n")
    (root / ".venv/bin/python").unlink()
    (root / ".venv/bin/python").symlink_to(alias / "bin" / interpreter.name)
    result = await executor(root, python_runtime_roots=[aliases]).execute(
        request(
            root,
            [
                "python",
                "-c",
                "import sys, os, only_project_dependency; print(sys.version.split()[0]); print(bool(os.statvfs(sys.base_prefix).f_flag & os.ST_RDONLY))",
            ],
        )
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[0].startswith("3.11.")
    assert result.stdout.splitlines()[1] == "True"


def test_broken_project_environment_never_falls_back_to_service_python(tmp_path):
    (tmp_path / ".venv").mkdir()
    policy = BubblewrapRuntimePolicy(
        workspace_root=tmp_path, include_python_environment=True
    )
    with pytest.raises(SandboxConfigurationError, match="pyvenv.cfg"):
        policy.project_environment(request(tmp_path, ["python", "--version"]))


def test_project_virtualenv_cannot_alias_another_directory(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / ".venv").symlink_to(Path(sys.prefix), target_is_directory=True)
    policy = BubblewrapRuntimePolicy(
        workspace_root=root, include_python_environment=True
    )
    with pytest.raises(SandboxConfigurationError, match="inside the selected project"):
        policy.project_environment(request(root, ["python", "--version"]))


def test_project_environment_cannot_request_an_unapproved_python_root(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", str(root / ".venv")],
        check=True,
        capture_output=True,
    )
    other = tmp_path / "unapproved/bin"
    other.mkdir(parents=True)
    shutil.copy2(sys.executable, other / "python")
    (root / ".venv/bin/python").unlink()
    (root / ".venv/bin/python").symlink_to(other / "python")
    (root / ".venv/pyvenv.cfg").write_text(f"home = {other}\n")
    policy = BubblewrapRuntimePolicy(
        workspace_root=root, include_python_environment=True
    )
    with pytest.raises(SandboxConfigurationError, match="not approved"):
        policy.project_environment(request(root, ["python", "--version"]))


@pytest.mark.asyncio
async def test_project_bins_follow_the_selected_working_directory(tmp_path):
    root = tmp_path / "project"
    nested = root / "frontend"
    binaries = nested / "node_modules/.bin"
    binaries.mkdir(parents=True)
    probe = binaries / "project-build"
    probe.write_text("#!/bin/sh\necho nested-project\n")
    probe.chmod(0o700)
    call = request(root, ["project-build"])
    call.command.cwd = "/workspace/frontend"
    result = await executor(root).execute(call)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "nested-project\n"


@pytest.mark.asyncio
async def test_copied_project_interpreters_use_their_original_python_runtime(
    python311_project, tmp_path
):
    source = (python311_project / ".venv/bin/python").resolve()
    root = tmp_path / "copied-project"
    root.mkdir()
    subprocess.run(
        [str(source), "-m", "venv", "--without-pip", "--copies", str(root / ".venv")],
        check=True,
        capture_output=True,
    )
    result = await executor(root).execute(
        request(
            root,
            [
                "python",
                "-c",
                "import sys; print(sys.version.split()[0]); print(sys.prefix)",
            ],
        )
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[0].startswith("3.11.")
    assert result.stdout.splitlines()[1] == "/workspace/.venv"


@pytest.mark.asyncio
async def test_shell_timeout_override_cannot_raise_runtime_ceiling(tmp_path):
    from EvernightAI.core.domain.tool import ToolManager, ToolRegister
    from EvernightAI.core.error.tool import ToolExecutionError
    from EvernightAI.core.schema.sandbox import SandboxResourceLimits
    from EvernightAI.core.schema.tool import ToolCall
    from EvernightAI.infra.registrations.tool.restricted_shell import (
        register_restricted_shell_tool,
    )

    register = ToolRegister()
    register_restricted_shell_tool(
        register,
        allowed_commands={"python"},
        working_directory=tmp_path,
        timeout_seconds=0.01,
        sandbox=executor(tmp_path, limits=SandboxResourceLimits(timeout_seconds=0.2)),
    )
    with pytest.raises(ToolExecutionError, match="timed out"):
        await ToolManager(register).execute(
            ToolCall(
                tool_call_id="bounded-timeout",
                tool_call={
                    "name": "restricted_shell",
                    "arguments": {
                        "command": ["python", "-c", "import time; time.sleep(3)"],
                        "timeout_seconds": 300,
                    },
                },
                metadata={"approved": True},
            )
        )
