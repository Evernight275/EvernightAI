import hashlib
import secrets
from collections.abc import Callable
from datetime import datetime, timezone
from uuid import uuid4

from EvernightAI.core.error.auth import AuthRequiredError
from EvernightAI.core.error.base import NotFoundError, ValidationError
from EvernightAI.core.protocol.api_key import (
    ApiKeyManagerProtocol,
    ApiKeyRegisterProtocol,
)
from EvernightAI.core.protocol.auth import AuthDeviceProtocol
from EvernightAI.core.schema.api_key import ApiKeyInfo, IssuedApiKey
from EvernightAI.core.schema.auth import Principal


class ApiKeyManager(ApiKeyManagerProtocol):
    def __init__(
        self,
        register: ApiKeyRegisterProtocol,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._register = register
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def issue(
        self, owner_id: str, name: str, *, expires_at: datetime | None = None
    ) -> IssuedApiKey:
        name = name.strip()
        if not name or len(name) > 120:
            raise ValidationError("API key name must contain 1 to 120 characters")
        now = self._clock()
        if expires_at is not None:
            if expires_at.tzinfo is None:
                raise ValidationError("API key expiry must include a timezone")
            if expires_at <= now:
                raise ValidationError("API key expiry must be in the future")
        api_key = "ena_" + secrets.token_urlsafe(32)
        info = ApiKeyInfo(
            key_id=uuid4().hex,
            owner_id=owner_id,
            name=name,
            prefix=api_key[:12],
            created_at=now,
            expires_at=expires_at,
        )
        self._register.create(info, _digest(api_key))
        return IssuedApiKey(api_key=api_key, key=info)

    def list_keys(self, owner_id: str) -> list[ApiKeyInfo]:
        return self._register.list_keys(owner_id)

    def revoke(self, owner_id: str, key_id: str) -> None:
        if not self._register.revoke(owner_id, key_id, self._clock()):
            raise NotFoundError("API key not found")

    def owner_for_key(self, api_key: str) -> str:
        if not api_key.startswith("ena_"):
            raise AuthRequiredError("Invalid API key")
        info = self._register.get_by_digest(_digest(api_key))
        if (
            info is None
            or info.revoked_at is not None
            or (info.expires_at is not None and info.expires_at <= self._clock())
        ):
            raise AuthRequiredError("Invalid API key")
        return info.owner_id


class ManagedApiKeyAuthDevice(AuthDeviceProtocol):
    def __init__(
        self, manager: ApiKeyManagerProtocol, principals: list[Principal]
    ) -> None:
        self._manager = manager
        self._principals = {
            principal.principal_id: principal for principal in principals
        }

    def principal(self, credential: object) -> Principal:
        if not isinstance(credential, str) or not credential:
            raise AuthRequiredError("Authentication required")
        owner_id = self._manager.owner_for_key(credential)
        principal = self._principals.get(owner_id)
        if principal is None:
            raise AuthRequiredError("Invalid API key")
        return principal.model_copy(deep=True)


def _digest(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()
