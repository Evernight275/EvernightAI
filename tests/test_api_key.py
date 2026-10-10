import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from EvernightAI.core.domain.api_key import ApiKeyManager, ManagedApiKeyAuthDevice
from EvernightAI.core.error.auth import AuthRequiredError
from EvernightAI.core.error.base import NotFoundError, ValidationError
from EvernightAI.core.schema.auth import Principal
from EvernightAI.infra.adapters.api_key import SQLiteApiKeyRegister
from EvernightAI.infra.sqlite import connect_sqlite


def test_keys_persist_as_digests_and_revocation_survives_restart(
    tmp_path: Path,
) -> None:
    path = tmp_path / "keys.sqlite3"
    register = SQLiteApiKeyRegister(path)
    try:
        manager = ApiKeyManager(register)
        issued = manager.issue("alice", " automation ")
        other = manager.issue("bob", "other")
        assert issued.api_key != other.api_key
        assert issued.key.name == "automation"
        assert manager.owner_for_key(issued.api_key) == "alice"
        assert [key.key_id for key in manager.list_keys("alice")] == [issued.key.key_id]
        connection = connect_sqlite(path)
        try:
            dump = "\n".join(connection.iterdump())
        finally:
            connection.close()
        assert issued.api_key not in dump
        assert hashlib.sha256(issued.api_key.encode()).hexdigest() in dump
        assert issued.api_key not in repr(issued)
        with pytest.raises(NotFoundError):
            manager.revoke("bob", issued.key.key_id)
        assert manager.owner_for_key(issued.api_key) == "alice"
    finally:
        register.close()
    reopened = SQLiteApiKeyRegister(path)
    try:
        manager = ApiKeyManager(reopened)
        assert manager.owner_for_key(issued.api_key) == "alice"
        manager.revoke("alice", issued.key.key_id)
        manager.revoke("alice", issued.key.key_id)
        with pytest.raises(AuthRequiredError):
            manager.owner_for_key(issued.api_key)
        assert manager.owner_for_key(other.api_key) == "bob"
        assert manager.list_keys("alice")[0].revoked_at is not None
    finally:
        reopened.close()


def test_expiry_and_invalid_names(tmp_path: Path) -> None:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    register = SQLiteApiKeyRegister(tmp_path / "keys.sqlite3")
    try:
        manager = ApiKeyManager(register, clock=lambda: now)
        for name in ["", "  ", "x" * 121]:
            with pytest.raises(ValidationError):
                manager.issue("alice", name)
        for expiry in [now, now - timedelta(seconds=1), now.replace(tzinfo=None)]:
            with pytest.raises(ValidationError):
                manager.issue("alice", "invalid", expires_at=expiry)
        issued = manager.issue(
            "alice", "temporary", expires_at=now + timedelta(seconds=1)
        )
        assert manager.owner_for_key(issued.api_key) == "alice"
        now += timedelta(seconds=1)
        with pytest.raises(AuthRequiredError):
            manager.owner_for_key(issued.api_key)
        with pytest.raises(AuthRequiredError):
            manager.owner_for_key("legacy-secret")
    finally:
        register.close()


def test_keys_use_current_account_permissions_and_reject_removed_accounts(
    tmp_path: Path,
) -> None:
    register = SQLiteApiKeyRegister(tmp_path / "keys.sqlite3")
    try:
        manager = ApiKeyManager(register)
        issued = manager.issue("alice", "automation")
        device = ManagedApiKeyAuthDevice(
            manager, [Principal(principal_id="alice", permissions=["tools:list"])]
        )
        principal = device.principal(issued.api_key)
        assert principal.permissions == ["tools:list"]
        principal.permissions.append("*")
        assert device.principal(issued.api_key).permissions == ["tools:list"]
        with pytest.raises(AuthRequiredError):
            ManagedApiKeyAuthDevice(manager, []).principal(issued.api_key)
    finally:
        register.close()
