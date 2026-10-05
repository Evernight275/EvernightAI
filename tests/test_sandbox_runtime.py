import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from EvernightAI.bootstrap.config import (
    create_runtime_from_config,
    create_sandbox_from_config,
)
from EvernightAI.core.error.sandbox import SandboxConfigurationError
from EvernightAI.core.error.sandbox import SandboxExecutionError
from EvernightAI.core.schema.sandbox import (
    SandboxCommand,
    SandboxExecutionRequest,
    SandboxFilesystemAccess,
    SandboxFilesystemMount,
    SandboxNetworkMode,
    SandboxPolicy,
    SandboxResourceLimits,
)
from EvernightAI.core.schema.tool import ToolCall
from EvernightAI.infra.adapters.sandbox.bubblewrap import BubblewrapSandboxExecutor
from EvernightAI.infra.adapters.sandbox.bubblewrap_policy import BubblewrapRuntimePolicy
from EvernightAI.interface.cli.config import parse_config
from EvernightAI.interface.cli.config import load_config


pytestmark = [
    pytest.mark.sandbox,
    pytest.mark.skipif(
        os.name != "posix" or shutil.which("bwrap") is None,
        reason="Linux Bubblewrap is required for OS isolation tests",
    ),
]


def request(
    root: Path, command: list[str], *, readonly: bool = False
) -> SandboxExecutionRequest:
    return SandboxExecutionRequest(
        request_id="sandbox-test",
        command=SandboxCommand(command=command, cwd="/workspace", timeout_seconds=10),
        policy=SandboxPolicy(
            command_allowlist=[command[0]],
            filesystem_mounts=[
                SandboxFilesystemMount(
                    host_path=str(root),
                    mount_path="/workspace",
                    access=SandboxFilesystemAccess.READ_ONLY
                    if readonly
                    else SandboxFilesystemAccess.READ_WRITE,
                )
            ],
            resource_limits=SandboxResourceLimits(
                timeout_seconds=10, max_output_chars=1000
            ),
        ),
    )


def executor(root: Path, **options) -> BubblewrapSandboxExecutor:
    return BubblewrapSandboxExecutor(
        runtime_policy=BubblewrapRuntimePolicy(
            workspace_root=root,
            include_python_environment=True,
            include_uv=True,
            **options,
        )
    )


@pytest.mark.asyncio
async def test_runtime_python_uv_and_secrets_are_isolated(tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    private = tmp_path / "private.txt"
    private.write_text("private canary")
    (work / "escape").symlink_to(private)
    monkeypatch.setenv("EVERNIGHT_SANDBOX_SECRET_CANARY", "private canary")
    sandbox = executor(work, protected_paths=[private])
    script = (
        "import json,os,pathlib,sys; "
        "print(json.dumps({'cwd':str(pathlib.Path.cwd()),"
        "'outside':pathlib.Path(sys.argv[1]).exists(),"
        "'symlink':pathlib.Path('escape').exists(),"
        "'env':'EVERNIGHT_SANDBOX_SECRET_CANARY' in os.environ})); "
        "pathlib.Path('output.txt').write_text('ok')"
    )
    result = await sandbox.execute(
        request(work, ["python", "-c", script, str(private)])
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "cwd": "/workspace",
        "outside": False,
        "symlink": False,
        "env": False,
    }
    assert (work / "output.txt").read_text() == "ok"
    version = await sandbox.execute(request(work, ["uv", "--version"]))
    assert version.returncode == 0, version.stderr
    assert version.stdout.startswith("uv ")
    alias = await sandbox.execute(request(work, [".venv/bin/python", "--version"]))
    assert alias.returncode == 0, alias.stderr
    assert alias.stdout.startswith("Python ")
    uv_python = await sandbox.execute(
        request(
            work,
            [
                "uv",
                "run",
                "--active",
                "--no-project",
                "--no-sync",
                "python",
                "-c",
                "print('uv-python')",
            ],
        )
    )
    assert uv_python.returncode == 0, uv_python.stderr
    assert uv_python.stdout == "uv-python\n"


@pytest.mark.asyncio
async def test_workspace_readonly_and_runtime_readonly_are_enforced(tmp_path):
    sandbox = executor(tmp_path)
    result = await sandbox.execute(
        request(
            tmp_path,
            [
                "python",
                "-c",
                (
                    "import os,pathlib; print(bool(os.statvfs('/usr').f_flag & os.ST_RDONLY)); "
                    f"print(bool(os.statvfs({sys.prefix!r}).f_flag & os.ST_RDONLY)); "
                    "pathlib.Path('blocked').write_text('no')"
                ),
            ],
            readonly=True,
        )
    )
    assert result.returncode != 0
    assert result.stdout.splitlines() == ["True", "True"]
    assert not (tmp_path / "blocked").exists()


@pytest.mark.asyncio
@pytest.mark.skipif(shutil.which("node") is None, reason="Installed Node is required")
async def test_optional_node_mount_supports_pyright_without_exposing_its_directory(
    tmp_path,
):
    sandbox = executor(tmp_path, include_node=True)
    result = await sandbox.execute(
        request(tmp_path, [".venv/bin/pyright", "--version"])
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("pyright ")
    node_path = shutil.which("node")
    assert node_path is not None
    node_directory = Path(node_path).resolve().parent
    visibility = await sandbox.execute(
        request(
            tmp_path,
            [
                "python",
                "-c",
                f"from pathlib import Path; print(Path({str(node_directory)!r}).exists())",
            ],
        )
    )
    if not node_directory.is_relative_to(
        Path("/usr")
    ) and not node_directory.is_relative_to(Path(sys.prefix)):
        assert visibility.stdout == "False\n"


@pytest.mark.asyncio
async def test_network_is_disabled_even_if_a_tool_requests_access(tmp_path):
    async def handle(reader, writer):
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    try:
        port = server.sockets[0].getsockname()[1]
        _, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.close()
        await writer.wait_closed()
        probe = request(
            tmp_path,
            [
                "python",
                "-c",
                (
                    "import socket; s=socket.socket(); s.settimeout(1); "
                    f"s.connect(('127.0.0.1', {port}))"
                ),
            ],
        )
        probe.policy.network_mode = SandboxNetworkMode.UNRESTRICTED
        result = await executor(tmp_path).execute(probe)
        assert result.returncode != 0
        assert "ConnectionRefusedError" in result.stderr
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_request_cannot_mount_outside_the_workspace_or_include_secrets(tmp_path):
    root = tmp_path / "work"
    root.mkdir()
    private = root / "runtime.sqlite3"
    private.write_text("canary")
    with pytest.raises(SandboxConfigurationError, match="protected"):
        executor(root, protected_paths=[private])
    with pytest.raises(SandboxConfigurationError, match="workspace_root"):
        await executor(root).execute(request(tmp_path, ["echo", "no"]))


def test_readonly_runtime_mounts_cannot_expose_service_data(tmp_path):
    private = tmp_path / "provider-key"
    private.write_text("canary")
    with pytest.raises(SandboxConfigurationError, match="protected"):
        BubblewrapRuntimePolicy(readonly_paths=[tmp_path], protected_paths=[private])


def test_readonly_runtime_mounts_cannot_have_a_writable_workspace_alias(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    with pytest.raises(SandboxConfigurationError, match="outside workspace_root"):
        BubblewrapRuntimePolicy(workspace_root=work, readonly_paths=[work])


@pytest.mark.asyncio
async def test_workspace_symlink_swap_is_rejected_at_execution(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    private = tmp_path / "private"
    private.mkdir()
    sandbox = executor(work, protected_paths=[private])
    work.rmdir()
    work.symlink_to(private, target_is_directory=True)
    with pytest.raises(SandboxConfigurationError, match="workspace_root"):
        await sandbox.execute(request(work, ["echo", "no"]))


@pytest.mark.asyncio
async def test_resource_limits_cannot_be_increased_inside_the_sandbox(tmp_path):
    limits = SandboxResourceLimits(
        timeout_seconds=10,
        memory_bytes=128 * 1024 * 1024,
        max_processes=256,
        cpu_seconds=5,
        file_size_bytes=1024,
    )
    sandbox = executor(tmp_path, limits=limits)
    probe = request(
        tmp_path,
        [
            "python",
            "-c",
            (
                "import json,resource; "
                "print(json.dumps([resource.getrlimit(v) for v in [resource.RLIMIT_AS,"
                "resource.RLIMIT_NPROC,resource.RLIMIT_CPU,resource.RLIMIT_FSIZE]])); "
                "resource.setrlimit(resource.RLIMIT_AS, (2**32,2**32))"
            ),
        ],
    )
    probe.policy.resource_limits.memory_bytes = 2**32
    result = await sandbox.execute(probe)
    assert result.stdout, result.stderr
    assert json.loads(result.stdout) == [
        [128 * 1024 * 1024] * 2,
        [256] * 2,
        [5] * 2,
        [1024] * 2,
    ]
    assert result.returncode != 0
    assert "not allowed" in result.stderr
    file_write = await sandbox.execute(
        request(
            tmp_path,
            [
                "python",
                "-c",
                (
                    "from pathlib import Path; Path('large-file').write_bytes(b'x' * 2048)"
                ),
            ],
        )
    )
    assert file_write.returncode != 0
    assert (tmp_path / "large-file").stat().st_size <= 1024
    allocate = await sandbox.execute(
        request(tmp_path, ["python", "-c", "bytearray(256 * 1024 * 1024)"])
    )
    assert allocate.returncode != 0
    assert "MemoryError" in allocate.stderr


@pytest.mark.asyncio
async def test_cpu_time_limit_stops_a_busy_loop(tmp_path):
    sandbox = executor(
        tmp_path, limits=SandboxResourceLimits(timeout_seconds=10, cpu_seconds=1)
    )
    result = await sandbox.execute(
        request(
            tmp_path, ["python", "-c", "print('busy', flush=True)\nwhile True: pass"]
        )
    )
    assert result.stdout == "busy\n", result.stderr
    assert result.returncode != 0


@pytest.mark.asyncio
async def test_process_limit_prevents_forking(tmp_path):
    sandbox = executor(
        tmp_path, limits=SandboxResourceLimits(timeout_seconds=10, max_processes=1)
    )
    result = await sandbox.execute(
        request(
            tmp_path,
            ["python", "-c", "import os; print('fork', flush=True); os.fork()"],
        )
    )
    assert result.stdout == "fork\n", result.stderr
    assert result.returncode != 0
    assert "Resource temporarily unavailable" in result.stderr


@pytest.mark.asyncio
async def test_large_output_without_newlines_is_drained_and_bounded(tmp_path):
    result = await executor(tmp_path).execute(
        request(
            tmp_path,
            [
                "python",
                "-c",
                "import sys; sys.stdout.write('汉' * 100000); sys.stderr.write('字' * 100000)",
            ],
        )
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "汉" * 1000
    assert result.stderr == "字" * 1000
    assert result.truncated
    assert sum(len(event.text) for event in result.events) <= 1000


@pytest.mark.asyncio
async def test_shell_project_and_git_use_the_same_configured_sandbox(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    subprocess.run(["git", "init", str(work)], check=True, capture_output=True)
    private = tmp_path / "private.txt"
    private.write_text("canary")
    subprocess.run(
        ["git", "-C", str(work), "config", "user.name", "Sandbox Test"], check=True
    )
    subprocess.run(
        ["git", "-C", str(work), "config", "user.email", "sandbox@example.test"],
        check=True,
    )
    (work / "note.txt").write_text("hello")
    hook = work / ".git" / "hooks" / "pre-commit"
    hook.write_text(
        "#!/bin/sh\n"
        f"if [ -e '{private}' ]; then exit 42; fi\n"
        "printf 'isolated' > hook-marker\n"
    )
    hook.chmod(0o700)
    config = parse_config(
        {
            "runtime": {
                "database_path": str(tmp_path / "runtime.sqlite3"),
                "sandbox_backend": "bubblewrap",
                "sandbox": {
                    "workspace_root": str(work),
                    "protected_paths": [str(private)],
                },
            },
            "tools": {
                "shell": {
                    "enabled": True,
                    "working_directory": str(work),
                    "allowed_commands": ["python"],
                },
                "git": {"enabled": True, "repository_directory": str(work)},
                "project": {
                    "enabled": True,
                    "working_directory": str(work),
                    "commands": {
                        "probe": [
                            "python",
                            "-c",
                            f"from pathlib import Path; print(Path({str(private)!r}).exists())",
                        ],
                    },
                },
            },
        }
    )
    runtime = create_runtime_from_config(config)
    try:
        for name, arguments in [
            (
                "restricted_shell",
                {"command": ["python", "-c", "import os; print(os.getcwd())"]},
            ),
            ("run_project_task", {"task": "probe"}),
            ("git_status", {}),
        ]:
            result = await runtime.tools.execute(
                ToolCall(
                    tool_call_id=name,
                    tool_call={"name": name, "arguments": arguments},
                    metadata={"approved": True},
                )
            )
            assert result.tool_call_result["returncode"] == 0, result.tool_call_result[
                "stderr"
            ]
            if name == "restricted_shell":
                assert result.tool_call_result["stdout"] == "/workspace\n"
            if name == "run_project_task":
                assert result.tool_call_result["stdout"] == "False\n"
        committed = await runtime.tools.execute(
            ToolCall(
                tool_call_id="commit",
                tool_call={
                    "name": "git_commit",
                    "arguments": {"paths": ["note.txt"], "message": "sandbox commit"},
                },
                metadata={"approved": True},
            )
        )
        assert committed.tool_call_result["commit"]["returncode"] == 0, (
            committed.tool_call_result
        )
        assert (work / "hook-marker").read_text() == "isolated"
    finally:
        await runtime.close()


@pytest.mark.parametrize(
    "tool, directory_key",
    [
        ("shell", "working_directory"),
        ("filesystem", "root"),
        ("git", "repository_directory"),
        ("project", "working_directory"),
        ("web", "download_directory"),
    ],
)
def test_configuration_rejects_tools_pointing_to_the_service_directory(
    tmp_path, tool, directory_key
):
    config = parse_config(
        {
            "runtime": {
                "database_path": str(tmp_path / "private.sqlite3"),
                "sandbox_backend": "bubblewrap",
                "sandbox": {"workspace_root": str(tmp_path / "work")},
            },
            "tools": {tool: {"enabled": True, directory_key: str(tmp_path)}},
        }
    )
    with pytest.raises(SandboxConfigurationError, match="workspace_root"):
        create_runtime_from_config(config)
    assert not (tmp_path / "private.sqlite3").exists()


def test_loaded_configuration_file_is_protected_even_with_a_custom_name(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    path = work / "private-settings.toml"
    path.write_text(
        f'[runtime]\nsandbox_backend = "bubblewrap"\ndatabase_path = "{tmp_path / "db.sqlite3"}"\n'
        f'[runtime.sandbox]\nworkspace_root = "{work}"\n'
    )
    with pytest.raises(SandboxConfigurationError, match="protected"):
        create_sandbox_from_config(load_config(path))


@pytest.mark.asyncio
async def test_runtime_timeout_ceiling_cannot_be_overridden(tmp_path):
    sandbox = executor(tmp_path, limits=SandboxResourceLimits(timeout_seconds=0.2))
    with pytest.raises(SandboxExecutionError, match="timed out"):
        await sandbox.execute(
            request(tmp_path, ["python", "-c", "import time; time.sleep(10)"])
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("stop", ["timeout", "cancel"])
async def test_stop_terminates_descendants_that_create_a_new_session(tmp_path, stop):
    child = (
        "from pathlib import Path; import time; Path('ready').write_text('yes'); "
        "time.sleep(0.8); Path('leaked').write_text('yes')"
    )
    probe = request(
        tmp_path,
        [
            "python",
            "-c",
            f"import subprocess,time; subprocess.Popen(['python', '-c', {child!r}], start_new_session=True); time.sleep(10)",
        ],
    )
    probe.command.timeout_seconds = 0.5
    task = asyncio.create_task(executor(tmp_path).execute(probe))

    async def wait_ready():
        while not (tmp_path / "ready").exists():
            await asyncio.sleep(0.01)

    try:
        await asyncio.wait_for(wait_ready(), timeout=2)
        if stop == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(SandboxExecutionError, match="timed out"):
                await task
        await asyncio.sleep(0.9)
        assert not (tmp_path / "leaked").exists()
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


def test_missing_sandbox_executable_never_falls_back(tmp_path, monkeypatch):
    monkeypatch.setattr("EvernightAI.bootstrap.config.shutil.which", lambda name: None)
    config = parse_config({"runtime": {"sandbox_backend": "bubblewrap"}})
    with pytest.raises(SandboxConfigurationError, match="bwrap"):
        create_sandbox_from_config(config)


@pytest.mark.asyncio
async def test_added_project_is_the_only_mounted_workspace(tmp_path):
    from EvernightAI.infra.adapters.tool.workspace_directory import (
        WorkspaceDirectoryStore,
    )

    default = tmp_path / "default"
    project = tmp_path / "external"
    other = tmp_path / "other"
    for directory in (default, project, other):
        directory.mkdir()
    (project / "name.txt").write_text("external project")
    (other / "private.txt").write_text("not mounted")
    (project / "escape").symlink_to(other, target_is_directory=True)
    store = WorkspaceDirectoryStore(default, protected_paths=[other])
    sandbox = BubblewrapSandboxExecutor(
        runtime_policy=BubblewrapRuntimePolicy(
            workspace_root=default,
            workspace_directories=store,
            include_python_environment=True,
            protected_paths=[other],
        )
    )
    script = "from pathlib import Path; print(Path('name.txt').read_text()); print(Path('escape/private.txt').exists())"
    with pytest.raises(SandboxConfigurationError, match="added project"):
        await sandbox.execute(request(project, ["python", "-c", script]))
    store.add_project(str(project))
    result = await sandbox.execute(request(project, ["python", "-c", script]))
    assert result.returncode == 0, result.stderr
    assert result.stdout == "external project\nFalse\n"
    assert not (default / "name.txt").exists()
