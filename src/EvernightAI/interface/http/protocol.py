from collections.abc import Callable

from fastapi import Request

from EvernightAI.core.protocol.auth import AuthDeviceProtocol
from EvernightAI.core.protocol.interface import EvernightInterfaceProtocol
from EvernightAI.core.schema.auth import Principal


class HttpAuthDeviceProtocol(AuthDeviceProtocol):
    def principal_for_request(self, request: Request) -> Principal: ...

    def principal(self, credential: object) -> Principal: ...


type AuthorizedHttpInterfaceFactoryProtocol = Callable[
    [EvernightInterfaceProtocol, Principal],
    EvernightInterfaceProtocol,
]
