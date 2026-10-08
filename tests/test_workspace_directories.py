import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from EvernightAI.bootstrap.http import create_app
from EvernightAI.core.domain.tool import ToolManager, ToolRegister
from EvernightAI.core.error.base import ConflictError, ValidationError
from EvernightAI.core.error.tool import ToolPolicyError
from EvernightAI.core.schema.tool import ToolCall
from EvernightAI.infra.adapters.tool.workspace_directory import WorkspaceDirectoryStore
from EvernightAI.infra.registrations.tool.restricted_filesystem import (
    register_restricted_filesystem_tools,
)
from tests.symlinks import requires_symlinks


@requires_symlinks
def test_workspace_browse_create_and_reject_escape(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "note.txt").write_text("hello")
    (root / "external").symlink_to(tmp_path, target_is_directory=True)
    store = WorkspaceDirectoryStore(root)
    assert [item.name for item in store.browse(".").entries] == ["note.txt"]
    created = store.create(".", "项目")
    assert created.path == "项目"
    assert created.entries == []
    assert store.browse(".").entries[0].is_directory
    for path in ["..", str(tmp_path), "external"]:
        with pytest.raises(ValidationError):
            store.browse(path)
    for name in ["../escape", ".", "", "/absolute", "a/b"]:
        with pytest.raises(ValidationError):
            store.create(".", name)
    with pytest.raises(ConflictError):
        store.create(".", "项目")


def test_workspace_http_auth_and_creation(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    browse_root = Path(tmp_path.anchor) if tmp_path.drive else tmp_path
    monkeypatch.setenv("EVERNIGHTAI_HTTP_API_KEY", "test-key")
    monkeypatch.setenv("EVERNIGHTAI_HTTP_AUTH_PERMISSIONS", "workspaces:list")
    app = create_app(
        database_path=tmp_path / "runtime.db",
        filesystem_root=tmp_path,
        close_on_shutdown=False,
    )
    with TestClient(app) as client:
        assert client.get("/workspaces").status_code == 401
        headers = {"x-evernight-api-key": "test-key"}
        response = client.get("/workspaces", headers=headers)
        assert response.status_code == 200
        assert response.json()["root"] == str(browse_root)
        assert (
            client.post(
                "/workspaces", headers=headers, json={"name": "denied"}
            ).status_code
            == 403
        )
        assert not (tmp_path / "denied").exists()
    asyncio.run(app.state.interface.close())
    monkeypatch.setenv(
        "EVERNIGHTAI_HTTP_AUTH_PERMISSIONS", "workspaces:list,workspaces:create"
    )
    app = create_app(
        database_path=tmp_path / "runtime.db",
        filesystem_root=tmp_path,
        close_on_shutdown=False,
    )
    with TestClient(app) as client:
        response = client.post(
            "/workspaces", headers=headers, json={"path": str(tmp_path), "name": "new"}
        )
        assert response.status_code == 201
        assert response.json()["path"] == str(tmp_path / "new")
        assert (
            client.get(
                "/workspaces", params={"path": "../"}, headers=headers
            ).status_code
            == 400
        )
        assert (
            client.post(
                "/workspaces",
                headers=headers,
                json={"path": str(tmp_path), "name": "new"},
            ).status_code
            == 409
        )
    asyncio.run(app.state.interface.close())


@pytest.mark.asyncio
async def test_file_tools_bind_directory_per_call_and_reject_escape(
    tmp_path: Path,
) -> None:
    for name in ["one", "two"]:
        (tmp_path / name).mkdir()
        (tmp_path / name / "note.txt").write_text(name)
    (tmp_path / "note.txt").write_text("root")
    register = ToolRegister()
    register_restricted_filesystem_tools(register, root_directory=tmp_path)
    manager = ToolManager(register)

    def call(directory: str, path: str = "note.txt") -> ToolCall:
        return ToolCall(
            tool_call_id=directory,
            tool_call={
                "name": "read_text_file",
                "arguments": {"path": path, "_working_directory": "two"},
            },
            metadata={"working_directory": directory},
        )

    import asyncio

    first, second = await asyncio.gather(
        manager.execute(call("one")), manager.execute(call("two"))
    )
    assert first.tool_call_result["content"] == "one"
    assert second.tool_call_result["content"] == "two"
    with pytest.raises(ToolPolicyError):
        await manager.execute(call(".."))
    from EvernightAI.core.error.tool import ToolExecutionError

    with pytest.raises(ToolExecutionError):
        await manager.execute(call("one", "../note.txt"))
    approval = manager.authorize(
        ToolCall(
            tool_call_id="write",
            tool_call={
                "name": "write_text_file",
                "arguments": {"path": "new.txt", "content": "test"},
            },
            metadata={"working_directory": "one"},
        )
    )
    assert approval.approval_request is not None
    assert approval.approval_request.metadata["working_directory"] == "one"


@pytest.mark.parametrize("relative", [False, True])
def test_toml_default_tools_root_is_independent_from_browser_root(
    tmp_path: Path,
    monkeypatch,
    relative: bool,
) -> None:
    from EvernightAI.bootstrap.http import create_app_from_config
    from EvernightAI.interface.cli.config import load_config

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    browse_root = Path(tmp_path.anchor) if tmp_path.drive else tmp_path
    root = tmp_path / "workspaces"
    root.mkdir()
    (root / "note.txt").write_text("configured workspace", encoding="utf-8")
    config_dir = tmp_path / "configuration"
    config_dir.mkdir()
    config_path = config_dir / "config.toml"
    configured_root = "workspaces" if relative else root.as_posix()
    config_path.write_text(
        "[runtime]\n"
        f'database_path = "{(tmp_path / "runtime.db").as_posix()}"\n'
        "[tools.filesystem]\n"
        "enabled = true\n"
        f'root = "{configured_root}"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EVERNIGHTAI_FILESYSTEM_ROOT", str(config_dir))
    app = create_app_from_config(load_config(config_path), close_on_shutdown=False)
    try:
        with TestClient(app) as client:
            response = client.get("/workspaces")
            assert response.status_code == 200
            assert response.json()["root"] == str(browse_root)
            response = client.get("/workspaces", params={"path": str(root)})
            assert response.json()["root"] == str(browse_root)
            assert response.json()["path"] == str(root)
            assert response.json()["parent"] == str(tmp_path)
            assert not response.json()["requires_registration"]
            assert [entry["name"] for entry in response.json()["entries"]] == [
                "note.txt"
            ]
            assert (
                client.post(
                    "/workspaces", json={"path": str(root), "name": "new-project"}
                ).status_code
                == 201
            )
            assert client.portal is not None
            result = client.portal.call(
                app.state.interface.runtime.tools.execute,
                ToolCall(
                    tool_call_id="configured-root",
                    tool_call={
                        "name": "read_text_file",
                        "arguments": {"path": "note.txt"},
                    },
                ),
            )
            assert result.tool_call_result["content"] == "configured workspace"
            assert (root / "new-project").is_dir()
            assert not (config_dir / "new-project").exists()
    finally:
        asyncio.run(app.state.interface.close())


def test_host_browser_reaches_home_or_drive_without_expanding_tool_access(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    root = tmp_path / "default"
    root.mkdir()
    project = tmp_path / "projects" / "example"
    project.mkdir(parents=True)
    private = tmp_path / "service"
    private.mkdir()
    store = WorkspaceDirectoryStore(
        root, protected_paths=[private], browse_host_directories=True
    )
    boundary = Path(root.anchor) if root.drive else tmp_path
    opened = store.browse(str(root))
    assert opened.root == str(boundary)
    assert opened.parent == str(tmp_path)
    assert store.browse(str(boundary)).parent is None
    assert store.browse(".").path == str(boundary)
    assert store.resolve(".") == str(root)
    assert store.browse(str(project)).requires_registration
    with pytest.raises(ValidationError):
        store.resolve(str(project))
    created = store.create(str(project), "src")
    assert created.parent == str(project)
    registered = store.add_project(str(project))
    assert not registered.requires_registration
    assert registered.parent == str(project.parent)
    assert store.resolve(created.path) == str(project / "src")
    with pytest.raises(ValidationError):
        store.create(str(private), "blocked")
    assert not (private / "blocked").exists()
    with pytest.raises(ValidationError):
        store.add_project(str(private))
    with pytest.raises(ValidationError):
        store.browse("..")
    if not root.drive:
        with pytest.raises(ValidationError):
            store.browse(str(tmp_path.parent))


@requires_symlinks
def test_external_projects_persist_and_enforce_their_boundaries(tmp_path: Path) -> None:
    root = tmp_path / "default"
    project = tmp_path / "projects" / "现有项目"
    root.mkdir()
    project.mkdir(parents=True)
    private = tmp_path / "service"
    private.mkdir()
    (private / "runtime.db").touch()
    database = private / "runtime.db"
    store = WorkspaceDirectoryStore(
        root, database_path=database, protected_paths=[private]
    )
    try:
        with pytest.raises(ValidationError):
            store.browse(str(project))
        opened = store.add_project(str(project))
        assert opened.path == str(project)
        assert opened.root == str(project)
        assert opened.parent is None
        created = store.create(opened.path, "src")
        assert created.parent == str(project)
        assert store.resolve(created.path) == str(project / "src")
        with pytest.raises(ValidationError):
            store.add_project(str(tmp_path))
        with pytest.raises(ValidationError):
            store.add_project(str(private))
        (project / "escape").symlink_to(private, target_is_directory=True)
        with pytest.raises(ValidationError):
            store.resolve(str(project / "escape"))
        assert "escape" not in [
            entry.name for entry in store.browse(str(project)).entries
        ]
    finally:
        store.close()
    restored = WorkspaceDirectoryStore(
        root, database_path=database, protected_paths=[private]
    )
    try:
        assert {item.path for item in restored.list_projects()} == {
            str(root),
            str(project),
        }
        assert restored.browse(str(project)).root == str(project)
        moved = project.with_name("moved")
        project.rename(moved)
        project.symlink_to(private, target_is_directory=True)
        with pytest.raises(ValidationError):
            restored.resolve(str(project))
    finally:
        restored.close()


@pytest.mark.asyncio
async def test_all_project_tools_follow_each_calls_workspace(tmp_path: Path) -> None:
    import subprocess
    import sys

    from EvernightAI.bootstrap.runtime import register_builtin_tools

    default = tmp_path / "default"
    default.mkdir()
    projects = [tmp_path / "one", tmp_path / "two"]
    workspaces = WorkspaceDirectoryStore(default)
    for project in projects:
        project.mkdir()
        (project / "name.txt").write_text(project.name)
        (project / f"{project.name}.txt").touch()
        subprocess.run(["git", "init", "-q", str(project)], check=True)
        workspaces.add_project(str(project))
    register = ToolRegister()
    register_builtin_tools(
        register,
        filesystem_root=default,
        workspace_directories=workspaces,
        shell_allowed_commands={sys.executable},
        shell_working_directory=default,
        git_repository_directory=default,
        project_working_directory=default,
        project_commands={
            "where": [sys.executable, "-c", "import os; print(os.getcwd())"]
        },
    )
    manager = ToolManager(register)

    def call(project, name, arguments, *, selected=True):
        return ToolCall(
            tool_call_id=f"{project.name}-{name}",
            tool_call={
                "name": name,
                "arguments": {**arguments, "_working_directory": str(projects[1])},
            },
            metadata={
                "approved": True,
                **({"working_directory": str(project)} if selected else {}),
            },
        )

    async def inspect(project):
        read = await manager.execute(
            call(project, "read_text_file", {"path": "name.txt"})
        )
        shell = await manager.execute(
            call(
                project,
                "restricted_shell",
                {"command": [sys.executable, "-c", "import os; print(os.getcwd())"]},
            )
        )
        git = await manager.execute(call(project, "git_status", {}))
        task = await manager.execute(
            call(project, "run_project_task", {"task": "where"})
        )
        assert read.tool_call_result["content"] == project.name
        assert shell.tool_call_result["stdout"].strip() == str(project)
        assert task.tool_call_result["stdout"].strip() == str(project)
        assert f"{project.name}.txt" in git.tool_call_result["stdout"]
        assert git.tool_call_result["repository_directory"] == str(project)

    await asyncio.gather(*(inspect(project) for project in projects))
    (default / "name.txt").write_text("default")
    read = await manager.execute(
        call(projects[0], "read_text_file", {"path": "name.txt"}, selected=False)
    )
    assert read.tool_call_result["content"] == "default"
    for name, arguments in [
        ("read_text_file", {"path": "name.txt"}),
        ("restricted_shell", {"command": ["pwd"]}),
        ("git_status", {}),
        ("run_project_task", {"task": "where"}),
    ]:
        with pytest.raises(ToolPolicyError):
            await manager.execute(call(tmp_path, name, arguments))
    with pytest.raises(ToolPolicyError):
        await manager.execute(
            call(
                projects[0],
                "restricted_shell",
                {"command": ["pwd"], "cwd": str(projects[1])},
            )
        )
    with pytest.raises(ToolPolicyError):
        await manager.execute(call(projects[0], "git_status", {"project": "other"}))
    approval_call = call(
        projects[0], "write_text_file", {"path": "new.txt", "content": "hi"}
    )
    approval_call.metadata.pop("approved")
    decision = manager.authorize(approval_call)
    assert decision.approval_request is not None
    assert decision.approval_request.metadata["working_directory"] == str(projects[0])


def test_project_registration_requires_permission_and_persists(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    project = tmp_path / "existing"
    project.mkdir()
    monkeypatch.setenv("EVERNIGHTAI_HTTP_API_KEY", "test-key")
    headers = {"x-evernight-api-key": "test-key"}
    for permissions, expected in [
        ("workspaces:list,workspaces:create", 403),
        ("workspaces:list,workspaces:register", 201),
    ]:
        monkeypatch.setenv("EVERNIGHTAI_HTTP_AUTH_PERMISSIONS", permissions)
        app = create_app(
            database_path=tmp_path / "runtime.db",
            filesystem_root=root,
            close_on_shutdown=False,
        )
        try:
            with TestClient(app) as client:
                assert (
                    client.post(
                        "/workspaces/projects", json={"path": str(project)}
                    ).status_code
                    == 401
                )
                response = client.post(
                    "/workspaces/projects", headers=headers, json={"path": str(project)}
                )
                assert response.status_code == expected
                if expected == 201:
                    assert response.json()["path"] == str(project)
                    assert any(
                        item["path"] == str(project)
                        for item in client.get(
                            "/workspaces/projects", headers=headers
                        ).json()
                    )
        finally:
            asyncio.run(app.state.interface.close())
    app = create_app(
        database_path=tmp_path / "runtime.db",
        filesystem_root=root,
        close_on_shutdown=False,
    )
    try:
        with TestClient(app) as client:
            assert (
                client.get(
                    "/workspaces", headers=headers, params={"path": str(project)}
                ).status_code
                == 200
            )
            assert (
                client.post(
                    "/workspaces/projects",
                    headers=headers,
                    json={"path": str(tmp_path)},
                ).status_code
                == 400
            )
    finally:
        asyncio.run(app.state.interface.close())
