import asyncio
import base64
import json
import os
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from EvernightAI.application.agent import AgentRunApplication
from EvernightAI.bootstrap.interface import create_interface
from EvernightAI.bootstrap.runtime import create_sqlite_runtime
from EvernightAI.core.domain.auth import Authorizer, PermissionAuthPolicy
from EvernightAI.core.domain.authorized_interface import AuthorizedEvernightInterface
from EvernightAI.core.domain.file import FileArtifactStore, MAX_FILE_ARTIFACT_BYTES
from EvernightAI.core.error.base import ConflictError, NotFoundError, ValidationError
from EvernightAI.core.error.tool import ToolExecutionError, ToolPolicyError
from EvernightAI.core.schema.agent import AgentRunRequest, AgentRunStatus
from EvernightAI.core.schema.auth import Principal, PrincipalScope
from EvernightAI.core.schema.content import (
    ChatResponse,
    Content,
    ContentPart,
    ContentPartType,
    MessageRole,
)
from EvernightAI.core.schema.context import Context
from EvernightAI.core.schema.file import FileArtifact
from EvernightAI.core.schema.provider import ProviderConfig, ProviderType
from EvernightAI.core.schema.tool import ToolAccessMode, ToolCall
from EvernightAI.infra.adapters.tool.file_artifacts import SQLiteFileArtifactStore
from EvernightAI.interface.http.app import create_http_app
from EvernightAI.interface.http.auth import ApiKeyHttpAuthDevice
from EvernightAI.interface.http.schema import HttpApiKeyCredential
from tests.test_application_agent import ToolCallingProvider
from tests.test_image_generation import PNG


@pytest.fixture(params=["memory", "sqlite"])
def store(request: pytest.FixtureRequest, tmp_path: Path):
    result = (
        FileArtifactStore()
        if request.param == "memory"
        else SQLiteFileArtifactStore(tmp_path / "runtime.db")
    )
    yield result
    if isinstance(result, SQLiteFileArtifactStore):
        result.close()


def test_file_store_snapshots_are_immutable_and_owner_scoped(store) -> None:
    artifact = FileArtifact(
        name="plot.png", mime_type="image/png", size_bytes=3, owner_id="alice"
    )
    store.save(artifact, b"png")
    artifact.name = "changed"
    scope = PrincipalScope(owner_id="alice")
    assert store.get(artifact.artifact_id, principal_scope=scope).name == "plot.png"
    assert store.read(artifact.artifact_id, principal_scope=scope) == b"png"
    returned = store.get(artifact.artifact_id, principal_scope=scope)
    returned.owner_id = "bob"
    with pytest.raises(ConflictError):
        store.save(returned, b"new")
    for operation in [store.get, store.read]:
        with pytest.raises(NotFoundError):
            operation(
                artifact.artifact_id, principal_scope=PrincipalScope(owner_id="bob")
            )
        with pytest.raises(NotFoundError):
            operation("missing", principal_scope=scope)
    with pytest.raises(ValidationError):
        store.save(
            FileArtifact(name="wrong", mime_type="text/plain", size_bytes=9), b"short"
        )


def file_call(
    path: str, *, directory: str | None = None, owner: str = "alice", **arguments
) -> ToolCall:
    return ToolCall(
        tool_call_id="display",
        tool_call={"name": "display_file", "arguments": {"path": path, **arguments}},
        metadata={
            "owner_id": owner,
            **({"working_directory": directory} if directory else {}),
        },
    )


@pytest.mark.asyncio
async def test_display_file_follows_selected_project_and_survives_source_deletion_and_restart(
    tmp_path: Path,
) -> None:
    root, project = tmp_path / "default", tmp_path / "project"
    root.mkdir()
    project.mkdir()
    content = base64.b64decode(PNG)
    (project / "plot.png").write_bytes(content)
    runtime = create_sqlite_runtime(tmp_path / "runtime.db", filesystem_root=root)
    assert runtime.workspace_directories is not None
    runtime.workspace_directories.add_project(str(project))
    try:
        result = await runtime.tools.execute(
            file_call(
                "/workspace/plot.png",
                directory=str(project),
                title="分析图",
                filename="图表.png",
                _execution_context={"owner_id": "bob"},
                _working_directory=str(root),
            )
        )
        output = result.tool_call_result
        artifact_id = output["artifact_id"]
        assert output["preview_kind"] == "image"
        assert output["mime_type"] == "image/png"
        assert "base64_data" not in output
        assert PNG not in json.dumps(output)
        assert "owner_id" not in output
        artifact = runtime.file_artifacts.get(
            artifact_id, principal_scope=PrincipalScope(owner_id="alice")
        )
        assert artifact.owner_id == "alice"
        assert artifact.title == "分析图"
        assert artifact.name == "图表.png"
        (project / "plot.png").unlink()
        assert runtime.file_artifacts.read(artifact_id) == content
    finally:
        await runtime.close()
    restored = create_sqlite_runtime(tmp_path / "runtime.db", filesystem_root=root)
    try:
        info, saved = create_interface(restored).files.read_file(
            artifact_id, principal_scope=PrincipalScope(owner_id="alice")
        )
        assert saved == content
        assert info.name == "图表.png"
    finally:
        await restored.close()


@pytest.mark.asyncio
async def test_file_display_rejects_escape_special_files_size_and_tool_denial(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "secret.txt").write_text("private")
    (root / "escape").symlink_to(tmp_path / "secret.txt")
    (root / "ok.txt").write_text("hello")
    with (root / "large.bin").open("wb") as file:
        file.truncate(MAX_FILE_ARTIFACT_BYTES + 1)
    runtime = create_sqlite_runtime(tmp_path / "runtime.db", filesystem_root=root)
    try:
        for path in [
            "../secret.txt",
            str(tmp_path / "secret.txt"),
            "escape",
            ".",
            "missing",
            "\0",
        ]:
            with pytest.raises(ToolPolicyError):
                await runtime.tools.execute(file_call(path))
        if os.name == "posix":
            os.mkfifo(root / "fifo")
            with pytest.raises(ToolPolicyError):
                await runtime.tools.execute(file_call("fifo"))
        with pytest.raises(ToolExecutionError) as oversized:
            await runtime.tools.execute(file_call("large.bin"))
        assert "20 MiB" in str(oversized.value)
        runtime.tools.set_tool_policy(
            "display_file",
            ToolAccessMode.DENY,
            principal_scope=PrincipalScope(owner_id="alice"),
        )
        with pytest.raises(ToolPolicyError):
            await runtime.tools.execute(file_call("ok.txt"))
    finally:
        await runtime.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content,mime,preview",
    [
        (b"\x89PNG\r\n\x1a\n", "image/png", "image"),
        (b"\xff\xd8\xff", "image/jpeg", "image"),
        (b"GIF89a", "image/gif", "image"),
        (b"RIFF1234WEBP", "image/webp", "image"),
        (b"<script>alert(1)</script>", "image/png", "none"),
    ],
)
async def test_file_display_detects_image_content_and_keeps_active_content_download_only(
    tmp_path: Path, content: bytes, mime: str, preview: str
) -> None:
    (tmp_path / "file.png").write_bytes(content)
    runtime = create_sqlite_runtime(tmp_path / "runtime.db", filesystem_root=tmp_path)
    try:
        result = await runtime.tools.execute(
            file_call("file.png", filename='report\r\n".png')
        )
        assert result.tool_call_result["mime_type"] == mime
        assert result.tool_call_result["preview_kind"] == preview
        assert result.tool_call_result["name"] == "report___.png"
    finally:
        await runtime.close()


def test_file_http_requires_auth_permissions_and_ownership_and_forces_safe_downloads(
    tmp_path: Path,
) -> None:
    runtime = create_sqlite_runtime(tmp_path / "runtime.db")
    image = FileArtifact(
        name="图表.png",
        mime_type="image/png",
        size_bytes=3,
        preview_kind="image",
        owner_id="alice",
    )
    html = FileArtifact(
        name="页面.html", mime_type="text/html", size_bytes=13, owner_id="alice"
    )
    runtime.file_artifacts.save(image, b"png")
    runtime.file_artifacts.save(html, b"<html></html>")
    credentials = [
        HttpApiKeyCredential(
            api_key=name,
            principal=Principal(principal_id=owner, permissions=permissions),
        )
        for name, owner, permissions in [
            ("alice", "alice", ["files:get", "files:read"]),
            ("bob", "bob", ["files:get", "files:read"]),
            ("limited", "alice", ["files:get"]),
        ]
    ]
    app = create_http_app(
        create_interface(runtime),
        close_on_shutdown=False,
        auth_device=ApiKeyHttpAuthDevice(credentials),
        authorized_interface_factory=lambda interface, principal: (
            AuthorizedEvernightInterface(
                interface, Authorizer(PermissionAuthPolicy()), principal
            )
        ),
    )
    with TestClient(app) as client:
        image_path = f"/files/{image.artifact_id}"
        assert client.get(image_path).status_code == 401
        assert client.get(image_path + "/content").status_code == 401
        bob = {"x-evernight-api-key": "bob"}
        other_owner = client.get(image_path, headers=bob)
        assert other_owner.status_code == 404
        assert other_owner.headers["cache-control"] == "no-store"
        assert client.get(image_path + "/content", headers=bob).status_code == 404
        assert (
            client.get(
                image_path + "/content", headers={"x-evernight-api-key": "limited"}
            ).status_code
            == 403
        )
        alice = {"x-evernight-api-key": "alice"}
        metadata = client.get(image_path, headers=alice)
        assert metadata.json()["name"] == "图表.png"
        assert "owner_id" not in metadata.json()
        response = client.get(image_path + "/content", headers=alice)
        assert response.content == b"png"
        assert response.headers["content-type"] == "image/png"
        assert response.headers["content-disposition"].startswith("inline;")
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
        download = client.get(image_path + "/content?download=true", headers=alice)
        assert download.headers["content-disposition"].startswith("attachment;")
        assert (
            "filename*=UTF-8''%E5%9B%BE%E8%A1%A8.png"
            in download.headers["content-disposition"]
        )
        active = client.get(f"/files/{html.artifact_id}/content", headers=alice)
        assert active.headers["content-type"] == "application/octet-stream"
        assert active.headers["content-disposition"].startswith("attachment;")
        assert "sandbox" in active.headers["content-security-policy"]
    asyncio.run(runtime.close())


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.name != "posix", reason="Requires POSIX directory-relative file opens"
)
async def test_file_display_rejects_directory_symlink_swapped_during_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from EvernightAI.infra.adapters.tool import display_file

    root = tmp_path / "root"
    plots = root / "plots"
    plots.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (plots / "plot.txt").write_text("allowed")
    (outside / "plot.txt").write_text("private")
    open_file = display_file._open_file

    def swap(directory: Path, relative: Path, flags: int) -> int:
        plots.rename(root / "moved")
        plots.symlink_to(outside, target_is_directory=True)
        return open_file(directory, relative, flags)

    runtime = create_sqlite_runtime(tmp_path / "runtime.db", filesystem_root=root)
    monkeypatch.setattr(display_file, "_open_file", swap)
    try:
        with pytest.raises(ToolExecutionError, match="无法读取展示文件"):
            await runtime.tools.execute(file_call("plots/plot.txt"))
    finally:
        await runtime.close()


class DisplayFileProvider(ToolCallingProvider):
    def __init__(self) -> None:
        super().__init__()
        self.requests = []

    async def chat(self, request):
        self.requests.append(request)
        if request.messages[-1].role is MessageRole.TOOL:
            return ChatResponse(
                model_id=request.model_id,
                message=Content(
                    role=MessageRole.ASSISTANT,
                    content=[ContentPart(type=ContentPartType.TEXT, text="图表已显示")],
                ),
            )
        return ChatResponse(
            model_id=request.model_id,
            message=Content(
                role=MessageRole.ASSISTANT,
                tool_calls=[file_call("plot.png", directory="spoof", owner="bob")],
            ),
        )


@pytest.mark.asyncio
async def test_agent_file_reference_is_persisted_without_binary_model_content(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "plot.png").write_bytes(base64.b64decode(PNG))
    runtime = create_sqlite_runtime(tmp_path / "runtime.db", filesystem_root=root)
    provider = DisplayFileProvider()

    async def build(_config):
        return provider

    runtime.provider_factory.register(ProviderType.OPENAI, build)
    await runtime.providers.create(
        ProviderConfig(provider_id="main", name="Main", type=ProviderType.OPENAI)
    )
    scope = PrincipalScope(owner_id="alice")
    await runtime.contexts.create(
        Context(context_id="ctx", owner_id="alice"), principal_scope=scope
    )
    try:
        state = await AgentRunApplication(runtime).start(
            AgentRunRequest(
                provider_id="main",
                model_id="chat-model",
                context_id="ctx",
                owner_id="alice",
                working_directory=str(root),
                tools=[runtime.tool_register.get("display_file")],
                messages=[
                    Content(
                        role=MessageRole.USER,
                        content=[
                            ContentPart(type=ContentPartType.TEXT, text="展示图表")
                        ],
                    )
                ],
            ),
            principal_scope=scope,
        )
        assert state.status is AgentRunStatus.FINISHED
        outputs = [
            step.tool_result.tool_call_result
            for step in state.steps
            if step.tool_result
        ]
        assert len(outputs) == 1
        artifact_id = outputs[0]["artifact_id"]
        assert runtime.file_artifacts.get(artifact_id).owner_id == "alice"
        assert runtime.agent_state_register is not None
        persisted = runtime.agent_state_register.get_state(
            state.run_id, principal_scope=scope
        )
        assert artifact_id in persisted.model_dump_json()
        assert PNG not in persisted.model_dump_json()
        tool_messages = [
            part.text
            for request in provider.requests
            for item in request.messages
            if item.role is MessageRole.TOOL
            for part in item.content or []
        ]
        assert any(artifact_id in (text or "") for text in tool_messages)
        assert not any(PNG in (text or "") for text in tool_messages)
    finally:
        await runtime.close()
