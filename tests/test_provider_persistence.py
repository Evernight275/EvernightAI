import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
import os
from pathlib import Path
import sqlite3

import pytest
from fastapi.testclient import TestClient

from EvernightAI.bootstrap.interface import create_interface
from EvernightAI.bootstrap.runtime import create_sqlite_runtime
from EvernightAI.core.error.provider import ProviderConfigurationError
from EvernightAI.core.schema.provider import (
    ProviderConfig,
    ProviderConfigUpdate,
    ProviderType,
)
from EvernightAI.infra.adapters.providers.sqlite import SQLiteProviderConfigStore
from EvernightAI.interface.http.app import create_http_app
from tests.test_provider_domain import FakeProvider


def provider_config(key: str = "saved-provider-key") -> ProviderConfig:
    return ProviderConfig(
        provider_id="images",
        name="Image service",
        type=ProviderType.OPENAI,
        api_key=key,
        base_url="https://provider.example/v1",
    )


def test_provider_store_encrypts_credentials_and_restores_them(tmp_path: Path) -> None:
    database = tmp_path / "runtime.sqlite3"
    config = provider_config()
    assert config.api_key
    store = SQLiteProviderConfigStore(database)
    try:
        store.save(config)
        saved = store.get(config.provider_id)
        assert saved.api_key is None
        assert saved.api_key_secret_ref
        assert config.api_key not in saved.model_dump_json()
    finally:
        store.close()

    key_path = Path(f"{database}.provider-key")
    assert key_path.exists()
    if os.name == "posix":
        assert key_path.stat().st_mode & 0o777 == 0o600
    connection = sqlite3.connect(database)
    try:
        assert config.api_key not in "\n".join(connection.iterdump())
    finally:
        connection.close()

    restored = SQLiteProviderConfigStore(database)
    try:
        assert restored.resolve(saved.api_key_secret_ref) == config.api_key
        assert restored.get(config.provider_id).base_url == config.base_url
    finally:
        restored.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [True, False])
async def test_created_and_edited_provider_survives_runtime_restart(
    tmp_path: Path, enabled: bool
) -> None:
    database = tmp_path / "runtime.sqlite3"
    built: list[ProviderConfig] = []

    async def build(config: ProviderConfig) -> FakeProvider:
        built.append(config)
        return FakeProvider()

    first = create_sqlite_runtime(database)
    first.provider_factory.register(ProviderType.OPENAI, build)
    try:
        await first.initialize()
        await first.providers.create(provider_config())
        await first.providers.update(
            "images",
            ProviderConfigUpdate(
                name="Edited service",
                base_url="https://updated.example/v1",
                api_key="updated-provider-key",
                is_enabled=enabled,
            ),
        )
    finally:
        await first.close()

    built.clear()
    second = create_sqlite_runtime(database)
    second.provider_factory.register(ProviderType.OPENAI, build)
    try:
        await second.initialize()
        view = await second.providers.get_config("images")
        assert view.name == "Edited service"
        assert view.base_url == "https://updated.example/v1"
        assert view.is_enabled == enabled
        assert view.has_api_key
        assert "updated-provider-key" not in view.model_dump_json()
        if not enabled:
            assert built == []
            await second.providers.update(
                "images", ProviderConfigUpdate(is_enabled=True)
            )
        assert built[-1].api_key == "updated-provider-key"
        await second.providers.update(
            "images", ProviderConfigUpdate(name="Renamed after restart")
        )
        assert built[-1].api_key == "updated-provider-key"
        await second.providers.delete("images")
    finally:
        await second.close()

    third = create_sqlite_runtime(database)
    try:
        await third.initialize()
        assert await third.providers.list_infos() == []
    finally:
        await third.close()


@pytest.mark.parametrize("edit", [False, True])
def test_provider_http_create_and_edit_survive_application_restart(
    tmp_path: Path,
    edit: bool,
) -> None:
    database = tmp_path / "runtime.sqlite3"
    built: list[ProviderConfig] = []

    async def build(config: ProviderConfig) -> FakeProvider:
        built.append(config)
        return FakeProvider()

    @contextmanager
    def application_client() -> Iterator[TestClient]:
        runtime = create_sqlite_runtime(database)
        runtime.provider_factory.register(ProviderType.OPENAI, build)
        app = create_http_app(
            create_interface(runtime),
            initialize_handler=runtime.initialize,
            close_on_shutdown=False,
        )
        try:
            with TestClient(app) as client:
                yield client
        finally:
            asyncio.run(runtime.close())

    with application_client() as client:
        created = client.post(
            "/providers", json=provider_config().model_dump(mode="json")
        )
        assert created.status_code == 201
        if edit:
            updated = client.patch(
                "/providers/images",
                json={
                    "api_key": "replacement-key",
                    "model": {
                        "image-model": {
                            "model_id": "image-model",
                            "capabilities": ["image_generation"],
                        },
                    },
                },
            )
            assert updated.status_code == 200
    built.clear()
    with application_client() as client:
        providers = client.get("/providers").json()
        assert [item["provider_id"] for item in providers] == ["images"]
        if edit:
            assert providers[0]["model"]["image-model"]["capabilities"] == [
                "image_generation"
            ]
        view = client.get("/providers/images/config").json()
        assert view["has_api_key"]
        expected_key = "replacement-key" if edit else "saved-provider-key"
        assert expected_key not in str(view)
        assert built[-1].api_key == expected_key


@pytest.mark.parametrize("mode", ["missing", "invalid", "different"])
def test_missing_or_changed_key_file_does_not_replace_saved_credentials(
    tmp_path: Path, mode: str
) -> None:
    from cryptography.fernet import Fernet

    database = tmp_path / "runtime.sqlite3"
    store = SQLiteProviderConfigStore(database)
    try:
        store.save(provider_config())
        original = store.get("images")
        assert original.api_key_secret_ref
        key_path = Path(f"{database}.provider-key")
        if mode == "missing":
            key_path.unlink()
        else:
            key_path.write_bytes(
                b"invalid" if mode == "invalid" else Fernet.generate_key()
            )
        with pytest.raises(ProviderConfigurationError):
            store.resolve(original.api_key_secret_ref)
        with pytest.raises(ProviderConfigurationError):
            store.save(provider_config("replacement-key"))
        assert store.get("images") == original
        if mode == "missing":
            assert not key_path.exists()
    finally:
        store.close()


@pytest.mark.asyncio
async def test_failed_credential_save_keeps_live_and_persisted_provider(
    tmp_path: Path,
) -> None:
    database = tmp_path / "runtime.sqlite3"
    runtime = create_sqlite_runtime(database)
    built: list[FakeProvider] = []

    async def build(_config: ProviderConfig) -> FakeProvider:
        instance = FakeProvider()
        built.append(instance)
        return instance

    runtime.provider_factory.register(ProviderType.OPENAI, build)
    try:
        await runtime.providers.create(provider_config())
        assert runtime.provider_config_store
        original = runtime.provider_config_store.get("images")
        connection = sqlite3.connect(database)
        try:
            connection.execute("""
                CREATE TRIGGER fail_provider_save BEFORE UPDATE ON provider_configs
                BEGIN SELECT RAISE(ABORT, 'save failed'); END
            """)
            connection.commit()
        finally:
            connection.close()
        with pytest.raises(sqlite3.IntegrityError, match="save failed"):
            await runtime.providers.update(
                "images", ProviderConfigUpdate(api_key="new-key")
            )
        assert await runtime.providers.get("images") is built[0]
        assert not built[0].closed
        assert built[1].closed
        assert runtime.provider_config_store.get("images") == original
    finally:
        await runtime.close()


def test_memory_sqlite_store_keeps_its_encryption_key_in_memory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    store = SQLiteProviderConfigStore(":memory:")
    try:
        store.save(provider_config())
        saved = store.get("images")
        assert saved.api_key_secret_ref
        assert store.resolve(saved.api_key_secret_ref) == "saved-provider-key"
        assert list(tmp_path.iterdir()) == []
    finally:
        store.close()
