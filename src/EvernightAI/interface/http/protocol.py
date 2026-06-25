from collections.abc import Callable
from typing import Any, Protocol

from fastapi import Request

from EvernightAI.core.protocol.auth import AuthDeviceProtocol
from EvernightAI.core.protocol.interface import EvernightInterfaceProtocol
from EvernightAI.core.schema.auth import Principal


class HttpAuthDeviceProtocol(AuthDeviceProtocol):
    def principal_for_request(self, request: Request) -> Principal: ...

    def principal(self, credential: object) -> Principal: ...


class JwkClientProtocol(Protocol):
    def get_signing_key_from_jwt(self, token: str) -> Any: ...


type AuthorizedHttpInterfaceFactoryProtocol = Callable[
    [EvernightInterfaceProtocol, Principal],
    EvernightInterfaceProtocol,
]
