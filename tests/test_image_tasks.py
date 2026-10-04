import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import pytest

from EvernightAI.application.image import ImageApplication
from EvernightAI.application.image_task import ImageTaskApplication
from EvernightAI.application.session import SessionApplication
from EvernightAI.bootstrap.interface import create_interface
from EvernightAI.bootstrap.runtime import create_runtime, create_sqlite_runtime
from EvernightAI.core.domain.image_task import ImageTaskStore
from EvernightAI.core.error.image import (
    ImageTaskConflictError,
    ImageTaskLimitError,
    ImageTaskNotFoundError,
)
from EvernightAI.core.error.provider import ProviderRequestError
from EvernightAI.core.schema.auth import Principal, PrincipalScope
from EvernightAI.core.schema.image import (
    ImageEditInput,
    ImageEditRequest,
    ImageGenerationRequest,
)
from EvernightAI.core.schema.image_task import ImageTask, ImageTaskSubmit
from EvernightAI.core.schema.provider import ProviderConfig, ProviderType
from EvernightAI.core.schema.session import Session
from EvernightAI.infra.adapters.images.tasks import SQLiteImageTaskStore
from EvernightAI.infra.adapters.images.sqlite import SQLiteImageGenerationStore
from EvernightAI.infra.adapters.images.executor import SingleProcessImageTaskExecutor
from EvernightAI.core.domain.auth import Authorizer, PermissionAuthPolicy
from EvernightAI.core.domain.authorized_interface import AuthorizedEvernightInterface
from EvernightAI.interface.http.app import create_http_app
from EvernightAI.interface.http.auth import ApiKeyHttpAuthDevice
from EvernightAI.interface.http.schema import HttpApiKeyCredential
from tests.test_image_editing import EditProvider
from tests.test_image_generation import ImageProvider, PNG


def submission(**kwargs: Any) -> ImageTaskSubmit:
    return ImageTaskSubmit(
        provider_id="main",
        request=ImageGenerationRequest(model_id="image-model", prompt="A green leaf"),
        **kwargs,
    )


async def configured(runtime: Any, fake: ImageProvider) -> ImageTaskApplication:
    async def build(_config: ProviderConfig) -> ImageProvider:
        return fake

    runtime.provider_factory.register(ProviderType.OPENAI, build)
    await runtime.providers.create(
        ProviderConfig(provider_id="main", name="Main", type=ProviderType.OPENAI)
    )
    return ImageTaskApplication(runtime)


async def completed(
    app: ImageTaskApplication, task_id: str, scope: PrincipalScope | None = None
):
    async with asyncio.timeout(3):
        while True:
            task = app.get(task_id, principal_scope=scope)
            if task.status not in ("queued", "running"):
                return task
            await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_task_returns_before_generation_and_idempotent_replay_survives_restart(
    tmp_path: Path,
) -> None:
    path = tmp_path / "runtime.sqlite3"
    runtime = create_sqlite_runtime(path, include_agent_storage=False)
    fake = ImageProvider(blocked=True)
    app = await configured(runtime, fake)
    request = submission()
    scope = PrincipalScope(owner_id="alice")
    try:
        task = await app.submit(request, principal_scope=scope)
        await asyncio.wait_for(fake.started.wait(), 2)
        assert app.get(task.task_id, principal_scope=scope).status == "running"
        assert (
            await app.submit(request, principal_scope=scope)
        ).task_id == task.task_id
        fake.release.set()
        result = await completed(app, task.task_id, scope)
        assert result.status == "succeeded"
        assert result.record_id == task.task_id
        assert len(fake.requests) == 1
    finally:
        await runtime.close()
    tasks = SQLiteImageTaskStore(path)
    records = SQLiteImageGenerationStore(path)
    try:
        assert tasks.get(task.task_id, principal_scope=scope).status == "succeeded"
        saved = records.get(task.task_id, principal_scope=scope)
        assert saved.response.images[0].base64_data == PNG
        assert saved.owner_id == "alice"
        with pytest.raises(ImageTaskNotFoundError):
            tasks.get(task.task_id, principal_scope=PrincipalScope(owner_id="bob"))
        assert not tasks.list_tasks(
            limit=20, principal_scope=PrincipalScope(owner_id="bob")
        )
    finally:
        tasks.close()
        records.close()


@pytest.mark.asyncio
async def test_queued_task_resumes_but_shutdown_running_task_is_not_replayed(
    tmp_path: Path,
) -> None:
    path = tmp_path / "runtime.sqlite3"
    store = SQLiteImageTaskStore(path)
    queued = ImageTask(**submission().model_dump())
    old = ImageTask(**submission().model_dump())
    store.create(old)
    assert store.claim("dead-worker", datetime.now(timezone.utc) - timedelta(seconds=1))
    store.create(queued)
    store.close()
    runtime = create_sqlite_runtime(path, include_agent_storage=False)
    fake = ImageProvider(blocked=True)
    app = await configured(runtime, fake)
    try:
        await runtime.initialize()
        await asyncio.wait_for(fake.started.wait(), 2)
        assert app.get(old.task_id).status == "interrupted"
        assert len(fake.requests) == 1
    finally:
        await runtime.close()
    store = SQLiteImageTaskStore(path)
    try:
        assert store.get(queued.task_id).status == "interrupted"
        assert (
            store.claim(
                "new-worker", datetime.now(timezone.utc) + timedelta(seconds=30)
            )
            is None
        )
    finally:
        store.close()


@pytest.mark.parametrize("sqlite", [False, True])
def test_claim_leases_quota_conflicts_and_owner_isolation(
    tmp_path: Path, sqlite: bool
) -> None:
    store = (
        SQLiteImageTaskStore(tmp_path / "tasks.sqlite3") if sqlite else ImageTaskStore()
    )
    try:
        task = ImageTask(**submission().model_dump(), owner_id="alice")
        assert store.create(task)
        assert not store.create(task)
        with pytest.raises(ImageTaskConflictError):
            store.create(task.model_copy(update={"provider_id": "another"}))
        with pytest.raises(ImageTaskNotFoundError):
            store.create(task.model_copy(update={"owner_id": "bob"}))
        lease = datetime.now(timezone.utc) + timedelta(seconds=30)
        assert store.claim("worker-1", lease).task_id == task.task_id  # type: ignore[union-attr]
        assert store.claim("worker-2", lease) is None
        assert not store.renew(task.task_id, "worker-2", lease)
        assert not store.finish(
            task.model_copy(update={"status": "succeeded"}), "worker-2"
        )
        store.recover_expired(datetime.now(timezone.utc))
        assert store.get(task.task_id).status == "running"
        store.recover_expired(lease + timedelta(seconds=1))
        assert store.get(task.task_id).status == "interrupted"
        for _ in range(10):
            store.create(ImageTask(**submission().model_dump(), owner_id="alice"))
        with pytest.raises(ImageTaskLimitError):
            store.create(ImageTask(**submission().model_dump(), owner_id="alice"))
        assert store.create(ImageTask(**submission().model_dump(), owner_id="bob"))
    finally:
        if isinstance(store, SQLiteImageTaskStore):
            store.close()


@pytest.mark.asyncio
async def test_two_executors_do_not_repeat_provider_calls(tmp_path: Path) -> None:
    path = tmp_path / "tasks.sqlite3"
    first, second = SQLiteImageTaskStore(path), SQLiteImageTaskStore(path)
    calls: list[str] = []

    async def run(task: ImageTask) -> ImageTask:
        calls.append(task.task_id)
        await asyncio.sleep(0.01)
        return task.model_copy(update={"status": "succeeded"})

    executors = [
        SingleProcessImageTaskExecutor(store, run) for store in (first, second)
    ]
    ids = []
    try:
        for _ in range(5):
            task = ImageTask(**submission().model_dump())
            first.create(task)
            ids.append(task.task_id)
        for executor in executors:
            await executor.start()
        async with asyncio.timeout(3):
            while any(first.get(task_id).status != "succeeded" for task_id in ids):
                await asyncio.sleep(0.01)
        assert sorted(calls) == sorted(ids)
    finally:
        for executor in executors:
            await executor.close()
        first.close()
        second.close()


@pytest.mark.asyncio
async def test_failures_and_edits_are_saved_without_retries_and_deletion_removes_inputs() -> (
    None
):
    runtime = create_runtime()

    class FailureProvider(EditProvider):
        async def generate_images(self, request):
            self.requests.append(request)
            raise ProviderRequestError("Unsupported image model")

    fake = FailureProvider()
    app = await configured(runtime, fake)
    scope = PrincipalScope(owner_id="alice")
    try:
        edit = ImageTaskSubmit(
            provider_id="main",
            request=ImageEditRequest(
                model_id="image-model",
                prompt="Edit",
                images=[ImageEditInput(base64_data=PNG, mime_type="image/png")],
            ),
        )
        task = await app.submit(edit, principal_scope=scope)
        failed = await completed(app, task.task_id, scope)
        assert failed.status == "failed"
        assert failed.error_message == "Unsupported image model"
        assert len(fake.requests) == 1
        assert (await app.submit(edit, principal_scope=scope)).status == "failed"
        fake2 = EditProvider()
        await configured(runtime, fake2)
        task = await app.submit(
            edit.model_copy(update={"task_id": submission().task_id}),
            principal_scope=scope,
        )
        assert (await completed(app, task.task_id, scope)).status == "succeeded"
        saved = ImageApplication(runtime).get_record(
            task.task_id, principal_scope=scope
        )
        assert isinstance(saved.request, ImageEditRequest)
        ImageApplication(runtime).delete_record(task.task_id, principal_scope=scope)
        with pytest.raises(ImageTaskNotFoundError):
            app.get(task.task_id, principal_scope=scope)
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_http_task_disconnect_polling_and_session_ownership() -> None:
    runtime = create_runtime()
    fake = ImageProvider(blocked=True)
    app = await configured(runtime, fake)
    await SessionApplication(runtime).create_session(
        Session(
            session_id="alice-session", context_id="alice-context", owner_id="alice"
        )
    )
    interface = create_interface(runtime)
    auth = ApiKeyHttpAuthDevice(
        [
            HttpApiKeyCredential(
                api_key=name, principal=Principal(principal_id=name, permissions=["*"])
            )
            for name in ("alice", "bob")
        ]
    )
    http_app = create_http_app(
        interface,
        auth_device=auth,
        authorized_interface_factory=lambda current, principal: (
            AuthorizedEvernightInterface(
                current, Authorizer(PermissionAuthPolicy()), principal
            )
        ),
    )
    request = submission(session_id="alice-session")
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=http_app),
            base_url="http://test",
            headers={"x-evernight-api-key": "alice"},
        ) as client:
            result = await client.post(
                "/images/tasks", json=request.model_dump(mode="json")
            )
            assert result.status_code == 202
            assert result.headers["cache-control"] == "no-store"
            assert result.headers["location"].endswith(request.task_id)
            assert "base64_data" not in result.text
            await asyncio.wait_for(fake.started.wait(), 2)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=http_app),
            base_url="http://test",
            headers={"x-evernight-api-key": "bob"},
        ) as other:
            assert (
                await other.get(f"/images/tasks/{request.task_id}")
            ).status_code == 404
            assert (await other.get("/images/tasks")).json()["items"] == []
            assert (
                await other.post(
                    "/images/tasks",
                    json=submission(session_id="alice-session").model_dump(mode="json"),
                )
            ).status_code == 404
        fake.release.set()
        assert (
            await completed(app, request.task_id, PrincipalScope(owner_id="alice"))
        ).status == "succeeded"
        assert len(fake.requests) == 1
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=http_app),
            base_url="http://test",
            headers={"x-evernight-api-key": "alice"},
        ) as client:
            page = (await client.get("/images/tasks?session_id=alice-session")).json()
            assert page["items"][0]["record_id"] == request.task_id
            invalid = await client.post(
                "/images/tasks",
                json={**request.model_dump(mode="json"), "owner_id": "bob"},
            )
            assert invalid.status_code == 400
    finally:
        await runtime.close()


@pytest.mark.parametrize("sqlite", [False, True])
def test_task_pagination_and_renewed_lease_use_current_metadata(
    tmp_path: Path, sqlite: bool
) -> None:
    store = (
        SQLiteImageTaskStore(tmp_path / "tasks.sqlite3") if sqlite else ImageTaskStore()
    )
    try:
        base = datetime.now(timezone.utc)
        for index in range(25):
            task = ImageTask(
                **submission(session_id="session").model_dump(),
                owner_id="alice",
                status="succeeded",
                created_at=base + timedelta(seconds=index),
            )
            store.create(task)
        runtime = create_runtime()
        runtime._image_tasks = store
        app = ImageTaskApplication(runtime)
        scope = PrincipalScope(owner_id="alice")
        first = app.list(limit=20, session_id="session", principal_scope=scope)
        second = app.list(
            limit=20,
            cursor=first.next_cursor,
            session_id="session",
            principal_scope=scope,
        )
        assert len(first.items) == 20 and len(second.items) == 5
        assert not {task.task_id for task in first.items} & {
            task.task_id for task in second.items
        }
        assert second.next_cursor is None
        assert not app.list(session_id="other", principal_scope=scope).items
        pending = ImageTask(**submission().model_dump())
        store.create(pending)
        store.claim("worker", base + timedelta(seconds=1))
        renewed = base + timedelta(seconds=60)
        assert store.renew(pending.task_id, "worker", renewed)
        store.recover_expired(base + timedelta(seconds=2))
        assert store.get(pending.task_id).lease_expires_at == renewed
        assert store.get_summary(pending.task_id).status == "running"
    finally:
        if isinstance(store, SQLiteImageTaskStore):
            store.close()


@pytest.mark.asyncio
async def test_interruption_after_provider_response_retains_paid_result(
    tmp_path: Path,
) -> None:
    from EvernightAI.core.schema.image import GeneratedImage, ImageGenerationResponse
    from pydantic import HttpUrl

    started = asyncio.Event()

    class RemoteProvider(ImageProvider):
        async def generate_images(self, request):
            self.requests.append(request)
            return ImageGenerationResponse(
                model_id=request.model_id,
                images=[
                    GeneratedImage(url=HttpUrl("https://images.example/result.png"))
                ],
            )

    class BlockedArchive:
        async def archive(self, response):
            started.set()
            await asyncio.Future()
            return response

    runtime = create_sqlite_runtime(
        tmp_path / "runtime.sqlite3", include_agent_storage=False
    )
    runtime._image_archive = BlockedArchive()
    fake = RemoteProvider()
    app = await configured(runtime, fake)
    task = await app.submit(
        submission(), principal_scope=PrincipalScope(owner_id="alice")
    )
    await asyncio.wait_for(started.wait(), 2)
    assert runtime.image_task_executor is not None
    await runtime.image_task_executor.close()
    try:
        result = app.get(task.task_id, principal_scope=PrincipalScope(owner_id="alice"))
        assert result.status == "interrupted"
        assert result.record_id == task.task_id
        assert result.error_message and "仍可查看" in result.error_message
        assert len(fake.requests) == 1
        assert (
            ImageApplication(runtime).get_record(task.task_id).response.images[0].url
            is not None
        )
        ImageApplication(runtime).delete_record(
            task.task_id, principal_scope=PrincipalScope(owner_id="alice")
        )
        with pytest.raises(ImageTaskNotFoundError):
            app.get(task.task_id)
    finally:
        await runtime.close()
