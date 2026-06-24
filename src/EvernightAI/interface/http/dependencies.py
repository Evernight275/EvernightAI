from typing import Annotated, cast

from fastapi import Depends, Request

from EvernightAI.core.protocol.interface import EvernightInterfaceProtocol
from EvernightAI.interface.http.protocol import (
    AuthorizedHttpInterfaceFactoryProtocol,
    HttpAuthDeviceProtocol,
)


def get_interface(request: Request) -> EvernightInterfaceProtocol:
    interface = cast(EvernightInterfaceProtocol, request.app.state.interface)
    auth_device = cast(
        HttpAuthDeviceProtocol | None,
        getattr(request.app.state, "auth_device", None),
    )
    if auth_device is None:
        return interface

    factory = cast(
        AuthorizedHttpInterfaceFactoryProtocol,
        request.app.state.authorized_interface_factory,
    )
    return factory(interface, auth_device.principal_for_request(request))


InterfaceDependency = Annotated[EvernightInterfaceProtocol, Depends(get_interface)]
